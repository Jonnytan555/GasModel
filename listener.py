"""
listener.py — ActiveMQ subscriber that triggers gas demand forecast on new data.

Subscribes to all three data queues. When any scraper publishes new rows, this
listener wakes up, queries the DB for the latest features, runs both models,
and writes the updated forecast — then publishes to /queue/gas.forecast so
the dashboard can refresh.

Run:
  python listener.py   (runs until Ctrl+C)
"""

import os
import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import appsettings as settings
import logger
logger.setup_log(
    app="gas_listener",
    filename=str(settings.LOG_DIR / "gas_listener.log"),
    use_stream=True,
)
from db import get_engine
from forecast import run_forecast


_RECONNECT_DELAY = 10   # seconds between reconnect attempts


def _connect(conn) -> None:
    conn.connect(settings.MQ_USER, settings.MQ_PASS, wait=True)
    for i, queue in enumerate(settings.MQ_QUEUES_SUBSCRIBE, start=1):
        conn.subscribe(destination=queue, id=i, ack="auto")
        logging.info("[listener] Subscribed to %s", queue)
    logging.info("[listener] Waiting for data  (Ctrl+C to stop)")


def listen() -> None:
    import stomp

    engine = get_engine()

    class ForecastListener(stomp.ConnectionListener):

        def on_error(self, frame):
            logging.error("[listener] MQ error: %s", frame.body)

        def on_message(self, frame):
            source = frame.headers.get("destination", "unknown")
            logging.info("[listener] Message received from %s — running forecast", source)
            try:
                results = run_forecast(engine)
                if results:
                    logging.info("[listener] Forecast complete: %s",
                                 {r["model_name"]: r["forecast_demand_mcm"]
                                  for r in results})
            except Exception as e:
                logging.exception("[listener] Forecast failed: %s", e)

        def on_disconnected(self):
            logging.warning("[listener] Disconnected from broker")

    while True:
        conn = stomp.Connection([(settings.MQ_HOST, settings.MQ_PORT)])
        conn.set_listener("", ForecastListener())
        try:
            _connect(conn)
            while conn.is_connected():
                time.sleep(1)
            logging.warning("[listener] Connection lost — reconnecting in %ds", _RECONNECT_DELAY)
            time.sleep(_RECONNECT_DELAY)
        except KeyboardInterrupt:
            logging.info("[listener] Stopping.")
            try:
                conn.disconnect()
            except Exception:
                pass
            break
        except Exception as e:
            logging.error("[listener] Connection error: %s — retrying in %ds", e, _RECONNECT_DELAY)
            time.sleep(_RECONNECT_DELAY)


if __name__ == "__main__":
    listen()
