"""
forecast.py — Run 7-day demand forecast using all trained models.

Run:
  python forecast.py
"""

import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import appsettings as settings
from db import get_engine
from models import MODELS
from models.loader import GasForecastLoader
from models.pipeline import ForecastPipeline


def _load_models() -> list:
    from models.storage import model_exists
    models = []
    for Model in MODELS:
        path = f"{settings.MODELS_DIR}/{Model.name}.pkl"
        if not model_exists(path):
            logging.warning("[forecast] Model not found: %s — run train.py first", path)
            continue
        models.append(Model.load(path))
        logging.info("[forecast] Loaded %s", Model.name)
    return models


def run_forecast(engine, days: int = 7) -> list[dict]:
    import stomp, json

    models = _load_models()
    if not models:
        logging.error("[forecast] No trained models found")
        return []

    def publish(rows):
        conn = stomp.StompConnection12([(settings.MQ_HOST, settings.MQ_PORT)])
        conn.connect(settings.MQ_USER, settings.MQ_PASS, wait=True)
        conn.send(settings.MQ_QUEUE_FORECAST, json.dumps(rows, default=str))
        conn.disconnect()
        logging.info("[forecast] Published %d rows to %s", len(rows), settings.MQ_QUEUE_FORECAST)

    return ForecastPipeline(
        loader=GasForecastLoader(days=days),
        models=models,
        engine=engine,
        publish_handler=publish,
    ).run(feature_cols=settings.FEATURE_COLS)


if __name__ == "__main__":
    import logger
    logger.setup_log(
        app="gas_forecast",
        filename=str(settings.LOG_DIR / "gas_forecast.log"),
        use_stream=True,
    )
    run_forecast(get_engine(), days=7)
