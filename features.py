"""
features.py — Build feature matrix from GASMODEL DB for training and inference.

Training features (one row per gas day):
  hdd           Heating Degree Days = max(0, HDD_BASE - avg_t2m)
  avg_wind_ms   Average 10m wind speed across UK cities
  linepack      Linepack SOD (mcm) — proxy for storage / market tightness
  day_of_week   0=Monday … 6=Sunday
  is_weekend    1 if Saturday/Sunday
  month         1–12 for seasonality

Target: demand_mcm (NTS Actual Total Consumption)
"""

import logging
import numpy as np
import pandas as pd
import sqlalchemy as sa
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import appsettings as settings


def build_features(engine: sa.Engine) -> pd.DataFrame:
    """
    Join NationalGasData + ECMWFForecast + ENTSOG UMMs and engineer features.
    Returns a DataFrame sorted by gas_date, ready for train/test split.
    """

    # ── National Gas demand + linepack ────────────────────────────────────────
    ngt = pd.read_sql(sa.text("""
        SELECT
            CONVERT(date, applicable_at)                           AS gas_date,
            MAX(CASE WHEN data_item = 'actual_demand' THEN value END) AS demand_mcm,
            MAX(CASE WHEN data_item = 'linepack'      THEN value END) AS linepack,
            MAX(CASE WHEN data_item = 'demand_forecast' THEN value END) AS ngt_forecast_mcm
        FROM dbo.NationalGasData
        GROUP BY CONVERT(date, applicable_at)
    """), engine)
    ngt["gas_date"] = pd.to_datetime(ngt["gas_date"]).dt.date

    # ── Weather — daily average across all UK cities (step_hours=0 = observed) ─
    weather = pd.read_sql(sa.text("""
        SELECT
            CONVERT(date, CONVERT(varchar, run_date), 112) AS gas_date,
            AVG(t2m_c)   AS avg_t2m,
            AVG(wind_ms) AS avg_wind_ms
        FROM dbo.ECMWFForecast
        WHERE step_hours = 0
        GROUP BY CONVERT(date, CONVERT(varchar, run_date), 112)
    """), engine)
    weather["gas_date"] = pd.to_datetime(weather["gas_date"]).dt.date

    # ── ENTSOG UMMs — total unavailable capacity per day ─────────────────────
    try:
        umm = pd.read_sql(sa.text("""
            SELECT
                CONVERT(date, eventStart)          AS gas_date,
                SUM(unavailableCapacity)            AS umm_capacity_unavailable,
                COUNT(*)                            AS umm_count
            FROM dbo.ENTSOGUrgentMarketMessages
            WHERE eventStatus = 'Active' AND isArchived != 'Yes'
            GROUP BY CONVERT(date, eventStart)
        """), engine)
        umm["gas_date"] = pd.to_datetime(umm["gas_date"]).dt.date
    except Exception:
        umm = pd.DataFrame(columns=["gas_date", "umm_capacity_unavailable", "umm_count"])

    # ── Join ──────────────────────────────────────────────────────────────────
    df = ngt.merge(weather, on="gas_date", how="inner")
    df = df.merge(umm,     on="gas_date", how="left")
    df["umm_capacity_unavailable"] = df["umm_capacity_unavailable"].fillna(0)
    df["umm_count"]                = df["umm_count"].fillna(0)
    df["linepack"]                 = df["linepack"].ffill()

    # ── Feature engineering ───────────────────────────────────────────────────
    df["hdd"]         = np.maximum(0, settings.HDD_BASE - df["avg_t2m"])
    dates             = pd.to_datetime(df["gas_date"])
    df["day_of_week"] = dates.dt.dayofweek          # 0=Mon, 6=Sun
    df["is_weekend"]  = dates.dt.dayofweek.isin([5, 6]).astype(int)
    df["month"]       = dates.dt.month

    df = df.sort_values("gas_date").reset_index(drop=True)
    return df


def _open_meteo_forecast_weather(n_days: int = 7) -> pd.DataFrame:
    """
    Fetch hourly forecast from Open-Meteo for all UK cities, return daily
    averages per date. Returns DataFrame with columns: date, avg_t2m, avg_wind_ms.
    """
    import requests
    from datetime import date, timedelta

    url = "https://api.open-meteo.com/v1/forecast"
    city_frames = []

    for city, (lat, lon) in settings.LOCATIONS.items():
        resp = requests.get(url, params={
            "latitude":      lat,
            "longitude":     lon,
            "hourly":        "temperature_2m,windspeed_10m",
            "timezone":      "Europe/London",
            "forecast_days": n_days + 1,   # +1 includes today; we slice from D+1
        }, timeout=30)
        resp.raise_for_status()
        hourly = resp.json()["hourly"]
        df_h = pd.DataFrame({
            "date":    [t[:10] for t in hourly["time"]],
            "t2m_c":   hourly["temperature_2m"],
            "wind_ms": hourly["windspeed_10m"],
        })
        city_frames.append(df_h)

    if not city_frames:
        return pd.DataFrame()

    # Average across all cities for each hour, then aggregate to daily
    all_hours = pd.concat(city_frames)
    daily = (all_hours.groupby("date")
             .agg(avg_t2m=("t2m_c", "mean"), avg_wind_ms=("wind_ms", "mean"))
             .reset_index())

    # Keep only D+1 … D+n_days
    today = str(date.today())
    daily = daily[daily["date"] > today].head(n_days).reset_index(drop=True)
    return daily


def forecast_features_multi_day(engine: sa.Engine, days: int = 7) -> pd.DataFrame:
    """
    Build a feature row for each of the next `days` days.
    Weather source: ECMWF DB if available, else Open-Meteo.
    Linepack and UMMs held constant at latest known values.
    """
    from datetime import date, timedelta

    today = date.today()

    # ── Weather ───────────────────────────────────────────────────────────────
    ecmwf = pd.read_sql(sa.text("""
        SELECT
            CONVERT(date, DATEADD(hour, step_hours,
                CONVERT(datetime, CONVERT(varchar, run_date), 112))) AS forecast_date,
            AVG(t2m_c)   AS avg_t2m,
            AVG(wind_ms) AS avg_wind_ms
        FROM dbo.ECMWFForecast
        WHERE step_hours > 0
          AND run_date = (SELECT MAX(run_date) FROM dbo.ECMWFForecast WHERE step_hours > 0)
        GROUP BY DATEADD(hour, step_hours,
                     CONVERT(datetime, CONVERT(varchar, run_date), 112))
    """), engine)

    if not ecmwf.empty and ecmwf["avg_t2m"].notna().any():
        logging.info("[features] Using ECMWF forecast from DB for %d-day outlook", days)
        ecmwf["forecast_date"] = pd.to_datetime(ecmwf["forecast_date"]).dt.date
        ecmwf = ecmwf[ecmwf["forecast_date"] > today].sort_values("forecast_date")
        weather_by_date = {row["forecast_date"]: (row["avg_t2m"], row["avg_wind_ms"])
                           for _, row in ecmwf.iterrows()}
    else:
        logging.info("[features] No ECMWF in DB — fetching %d-day outlook from Open-Meteo", days)
        om = _open_meteo_forecast_weather(days)
        if om.empty:
            logging.error("[features] Open-Meteo forecast fetch failed")
            return pd.DataFrame()
        weather_by_date = {row["date"]: (row["avg_t2m"], row["avg_wind_ms"])
                           for _, row in om.iterrows()}

    # ── Linepack (latest known) ───────────────────────────────────────────────
    lp_row = pd.read_sql(sa.text("""
        SELECT TOP 1 value AS linepack
        FROM dbo.NationalGasData
        WHERE data_item = 'linepack'
        ORDER BY applicable_at DESC
    """), engine)
    linepack = float(lp_row["linepack"].iloc[0]) if not lp_row.empty else 0.0

    # ── Active UMMs (current snapshot) ───────────────────────────────────────
    umm_row = pd.read_sql(sa.text("""
        SELECT
            ISNULL(SUM(unavailableCapacity), 0) AS umm_capacity_unavailable,
            COUNT(*)                             AS umm_count
        FROM dbo.ENTSOGUrgentMarketMessages
        WHERE eventStatus = 'Active' AND isArchived != 'Yes'
    """), engine)
    umm_cap   = float(umm_row["umm_capacity_unavailable"].iloc[0])
    umm_count = float(umm_row["umm_count"].iloc[0])

    # ── Build one row per forecast day ────────────────────────────────────────
    rows = []
    for i in range(1, days + 1):
        target = today + timedelta(days=i)
        key    = str(target)
        if key not in weather_by_date:
            continue
        avg_t2m, avg_wind_ms = weather_by_date[key]
        rows.append({
            "gas_date":                 target,
            "avg_t2m":                  avg_t2m,
            "avg_wind_ms":              avg_wind_ms,
            "linepack":                 linepack,
            "umm_capacity_unavailable": umm_cap,
            "umm_count":                umm_count,
            "hdd":                      max(0.0, settings.HDD_BASE - avg_t2m),
            "day_of_week":              target.weekday(),
            "is_weekend":               int(target.weekday() >= 5),
            "month":                    target.month,
        })

    return pd.DataFrame(rows)


def latest_forecast_features(engine: sa.Engine) -> pd.DataFrame:
    """Single-row feature vector for D+1. Calls forecast_features_multi_day(days=1)."""
    return forecast_features_multi_day(engine, days=1)
