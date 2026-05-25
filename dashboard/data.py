"""
data.py — DB query helpers for the Dash dashboard.
All functions return DataFrames ready for Plotly.
"""

import sys
import pandas as pd
import sqlalchemy as sa
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db import get_engine


def _engine() -> sa.Engine:
    return get_engine()


def actuals_and_forecasts(days: int = 60) -> pd.DataFrame:
    """
    Returns one row per (gas_date, series) with columns:
      gas_date, series, value_mcm
    Series values: 'Actual', 'NGT Forecast', 'Linear Model', 'GBM Model'
    """
    engine = _engine()

    actuals = pd.read_sql(sa.text(f"""
        SELECT
            CONVERT(date, applicable_at) AS gas_date,
            MAX(CASE WHEN data_item = 'actual_demand'   THEN value END) AS actual,
            MAX(CASE WHEN data_item = 'demand_forecast' THEN value END) AS ngt_forecast
        FROM dbo.NationalGasData
        WHERE CONVERT(date, applicable_at) >= DATEADD(day, -{days}, CAST(GETDATE() AS date))
        GROUP BY CONVERT(date, applicable_at)
    """), engine)

    forecasts = pd.read_sql(sa.text(f"""
        SELECT forecast_date AS gas_date, model_name, forecast_demand_mcm
        FROM dbo.GasForecast
        WHERE CAST(forecast_date AS date) >= DATEADD(day, -{days}, CAST(GETDATE() AS date))
    """), engine)

    rows = []
    for _, r in actuals.iterrows():
        if pd.notna(r["actual"]):
            rows.append({"gas_date": r["gas_date"], "series": "Actual", "value_mcm": r["actual"]})
        if pd.notna(r["ngt_forecast"]):
            rows.append({"gas_date": r["gas_date"], "series": "NGT Forecast", "value_mcm": r["ngt_forecast"]})

    label_map = {"linear": "Linear Model", "gbm": "GBM Model"}
    for _, r in forecasts.iterrows():
        label = label_map.get(r["model_name"], r["model_name"])
        rows.append({"gas_date": r["gas_date"], "series": label,
                     "value_mcm": r["forecast_demand_mcm"]})

    df = pd.DataFrame(rows)
    if not df.empty:
        df["gas_date"] = pd.to_datetime(df["gas_date"])
    return df


def latest_forecasts() -> pd.DataFrame:
    """Latest D+1 forecast from each model."""
    engine = _engine()
    return pd.read_sql(sa.text("""
        SELECT model_name, forecast_demand_mcm, hdd, avg_wind_ms, forecast_date, created_at
        FROM dbo.GasForecast
        WHERE forecast_date = (SELECT MAX(forecast_date) FROM dbo.GasForecast)
    """), engine)


def active_umms() -> pd.DataFrame:
    """Currently active ENTSOG urgent market messages."""
    engine = _engine()
    try:
        return pd.read_sql(sa.text("""
            SELECT id, eventStatus, unavailableCapacity, eventStart, eventStop,
                   affectedAssetName, remarks
            FROM dbo.ENTSOGUrgentMarketMessages
            WHERE eventStatus = 'Active' AND isArchived != 'Yes'
            ORDER BY unavailableCapacity DESC
        """), engine)
    except Exception:
        return pd.DataFrame()


def supply_vs_demand(days: int = 30) -> pd.DataFrame:
    """Daily total supply and demand for bar chart."""
    engine = _engine()
    return pd.read_sql(sa.text(f"""
        SELECT
            CONVERT(date, applicable_at) AS gas_date,
            MAX(CASE WHEN data_item = 'actual_demand' THEN value END) AS demand_mcm,
            MAX(CASE WHEN data_item = 'total_supply'  THEN value END) AS supply_mcm,
            MAX(CASE WHEN data_item = 'linepack'      THEN value END) AS linepack
        FROM dbo.NationalGasData
        WHERE CONVERT(date, applicable_at) >= DATEADD(day, -{days}, CAST(GETDATE() AS date))
        GROUP BY CONVERT(date, applicable_at)
        ORDER BY gas_date
    """), engine)


def hdd_vs_demand() -> pd.DataFrame:
    """HDD vs actual demand scatter — shows temperature-demand relationship."""
    engine = _engine()
    weather = pd.read_sql(sa.text("""
        SELECT
            CONVERT(date, CONVERT(varchar, run_date), 112) AS gas_date,
            AVG(t2m_c) AS avg_t2m
        FROM dbo.ECMWFForecast
        WHERE step_hours = 0
        GROUP BY CONVERT(date, CONVERT(varchar, run_date), 112)
    """), engine)

    demand = pd.read_sql(sa.text("""
        SELECT CONVERT(date, applicable_at) AS gas_date,
               MAX(CASE WHEN data_item = 'actual_demand' THEN value END) AS demand_mcm
        FROM dbo.NationalGasData
        GROUP BY CONVERT(date, applicable_at)
    """), engine)

    df = weather.merge(demand, on="gas_date", how="inner").dropna()
    df["hdd"] = (15.5 - df["avg_t2m"]).clip(lower=0)
    df["gas_date"] = pd.to_datetime(df["gas_date"])
    return df


def multi_day_forecast() -> pd.DataFrame:
    """7-day demand forecast from each model, ordered by date."""
    engine = _engine()
    try:
        from datetime import date
        return pd.read_sql(sa.text("""
            SELECT forecast_date, model_name, forecast_demand_mcm, hdd, avg_wind_ms
            FROM dbo.GasForecast
            WHERE CAST(forecast_date AS date) >= CAST(GETDATE() AS date)
              AND created_at = (SELECT MAX(created_at) FROM dbo.GasForecast)
            ORDER BY forecast_date, model_name
        """), engine)
    except Exception:
        return pd.DataFrame()


def model_evaluation() -> pd.DataFrame:
    """Latest evaluation metrics from training runs."""
    engine = _engine()
    try:
        return pd.read_sql(sa.text("""
            SELECT model, rmse_mcm, mae_mcm, mape_pct, trained_at, train_rows, test_rows
            FROM dbo.ModelEvaluation
            WHERE trained_at = (SELECT MAX(trained_at) FROM dbo.ModelEvaluation)
        """), engine)
    except Exception:
        return pd.DataFrame()
