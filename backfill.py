"""
backfill.py — Load historical data into GASMODEL DB for model training.

Two data sources:
  1. National Gas REST API     → NationalGasData  (demand, linepack, supply)
     POST https://api.nationalgas.com/operationaldata/v1/publications/gasday
  2. Open-Meteo archive API    → ECMWFForecast     (temperature, wind)
     Free, no API key, historical weather at any lat/lon.

Run:
  python backfill.py           # last BACKFILL_YEARS years
  python backfill.py 2022-01-01 2024-12-31  # custom range
"""

import sys
import logging
import time
import pandas as pd
import sqlalchemy as sa
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, r"C:\Python\common_libraries\common-scraper\src")

import os
import logger

APP_NAME = "gas_backfill"
LOG_PATH = r"C:\Python\DataEngineering\GasModel\logs"

logger.setup_log(
    app=APP_NAME,
    filename=os.path.join(LOG_PATH, APP_NAME + ".log"),
    use_stream=True,
)

import appsettings as settings
from db import get_engine

from scraper.scraper import Scraper
from scraper.request.get_request import HttpGetRequestHandler
from scraper.request.post_request import HttpPostRequestHandler
from scraper.persistence.db_upsert_handler import DbUpsertHandler
from scraper.response.response_handler import ResponseHandler


# ── Response Handlers ──────────────────────────────────────────────────────────

class NgtResponseHandler(ResponseHandler):
    """
    Parses the National Gas REST API publications/gasday response.

    Response shape:
      [{"publicationId": "PUBOB637",
        "publications": [{"applicableFor": "2024-02-29", "value": "302.5", ...}]}]
    """

    def __init__(self, data_item_map: dict) -> None:
        super().__init__()
        self._id_to_name = {v: k for k, v in data_item_map.items()}

    def handle(self, response) -> pd.DataFrame:
        data = response.json()
        if not data:
            return pd.DataFrame()
        created_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for pub in data:
            pub_id    = pub.get("publicationId", "")
            data_item = self._id_to_name.get(pub_id, pub_id)
            for record in pub.get("publications", []):
                applicable_for = record.get("applicableFor", "")
                value          = record.get("value")
                if applicable_for and value is not None:
                    rows.append({
                        "applicable_at": applicable_for,
                        "data_item":     data_item,
                        "value":         float(value),
                        "unit":          "mcm/d",
                        "created_at":    created_at,
                    })
        return pd.DataFrame(rows)


class OpenMeteoResponseHandler(ResponseHandler):
    """
    Parses Open-Meteo archive hourly response into daily aggregates per city.
    """

    def __init__(self, city: str) -> None:
        super().__init__()
        self.city = city

    def handle(self, response) -> pd.DataFrame:
        hourly = response.json()["hourly"]
        df = pd.DataFrame({
            "time":    hourly["time"],
            "t2m_c":   hourly["temperature_2m"],
            "wind_ms": hourly["windspeed_10m"],
            "tp_mm":   hourly["precipitation"],
        })
        df["date"] = df["time"].str[:10]
        daily = df.groupby("date").agg(
            t2m_c=("t2m_c",   "mean"),
            wind_ms=("wind_ms", "mean"),
            tp_mm=("tp_mm",   "sum"),
        ).reset_index()

        created_at = datetime.now(timezone.utc).isoformat()
        daily["run_date"]   = daily["date"].str.replace("-", "")
        daily["location"]   = self.city
        daily["step_hours"] = 0
        daily["msl_hpa"]    = None
        daily["created_at"] = created_at
        return daily[["run_date", "location", "step_hours",
                      "t2m_c", "wind_ms", "tp_mm", "msl_hpa", "created_at"]]


# ── Backfill classes ───────────────────────────────────────────────────────────

class NationalGasBackfill:

    _URL = "https://api.nationalgas.com/operationaldata/v1/publications/gasday"
    _PUB_IDS = {
        "actual_demand":   "PUBOB637",  # Demand Actual, NTS, D+1
        "demand_forecast": "PUBOB28",   # Demand Forecast, NTS, hourly update
        "total_supply":    "PUBOB692",  # NTS System Input, Actual
        "linepack":        "PUBOB693",  # Opening linepack, actual
    }

    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    def run(self, start: date, end: date) -> None:
        logging.info("[NGT] Backfilling %s → %s", start, end)
        d = start.replace(day=1)
        while d <= end:
            month_end = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            chunk_end = min(month_end, end)
            for attempt in range(5):
                try:
                    Scraper(
                        request_handler=HttpPostRequestHandler(
                            url=self._URL,
                            json={
                                "fromDate":       d.isoformat(),
                                "toDate":         chunk_end.isoformat(),
                                "publicationIds": list(self._PUB_IDS.values()),
                                "latestValue":    "Y",
                            },
                            headers={"Content-Type": "application/json"},
                        ),
                        response_handler=NgtResponseHandler(data_item_map=self._PUB_IDS),
                        persistence_handler=DbUpsertHandler(
                            engine=self.engine,
                            table_name="NationalGasData",
                            schema="dbo",
                            key_cols=["applicable_at", "data_item"],
                        ),
                    ).scrape(dropNa=False)
                    break
                except Exception as e:
                    if "429" in str(e) and attempt < 4:
                        wait = 15 * (2 ** attempt)
                        logging.warning("[NGT] 429 rate limit — sleeping %ds (attempt %d/5)", wait, attempt + 1)
                        time.sleep(wait)
                    else:
                        logging.exception("[NGT] Failed for %s → %s", d, chunk_end)
                        break
            d = chunk_end + timedelta(days=1)
            time.sleep(2)


class OpenMeteoBackfill:

    _URL = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    def run(self, start: date, end: date) -> None:
        logging.info("[Weather] Backfilling %s → %s via Open-Meteo", start, end)
        for city, (lat, lon) in settings.LOCATIONS.items():
            try:
                Scraper(
                    request_handler=HttpGetRequestHandler(
                        url=self._URL,
                        params={
                            "latitude":   lat,
                            "longitude":  lon,
                            "start_date": start.isoformat(),
                            "end_date":   end.isoformat(),
                            "hourly":     "temperature_2m,windspeed_10m,precipitation",
                            "timezone":   "Europe/London",
                        },
                        timeout=60,
                    ),
                    response_handler=OpenMeteoResponseHandler(city=city),
                    persistence_handler=DbUpsertHandler(
                        engine=self.engine,
                        table_name="ECMWFForecast",
                        schema="dbo",
                        key_cols=["run_date", "location", "step_hours"],
                    ),
                ).scrape(dropNa=False)
            except Exception:
                logging.exception("[Weather] Failed for %s", city)
            time.sleep(0.3)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args  = sys.argv[1:]
    today = date.today()

    if len(args) >= 2:
        start = date.fromisoformat(args[0])
        end   = date.fromisoformat(args[1])
    else:
        start = today.replace(year=today.year - settings.BACKFILL_YEARS)
        end   = today - timedelta(days=1)

    logging.info("Backfilling %s → %s", start, end)
    engine = get_engine()

    NationalGasBackfill(engine).run(start, end)
    OpenMeteoBackfill(engine).run(start, end)
    logging.info("Backfill complete.")
