import os
from pathlib import Path

# ── Database ───────────────────────────────────────────────────────────────────
DB_HOST   = os.environ.get("DB_HOST",   "localhost")
DB_NAME   = os.environ.get("DB_NAME",   "GAS_MODEL")
DB_DRIVER = os.environ.get("DB_DRIVER", "ODBC Driver 17 for SQL Server")

# ── ActiveMQ ───────────────────────────────────────────────────────────────────
MQ_HOST = os.environ.get("MQ_HOST", "localhost")
MQ_PORT = int(os.environ.get("MQ_PORT", "61613"))
MQ_USER = os.environ.get("MQ_USER", "admin")
MQ_PASS = os.environ.get("MQ_PASS", "admin")

MQ_QUEUES_SUBSCRIBE = [
    "/queue/gas.national",
    "/queue/gas.entsog",
    "/queue/gas.weather",
]
MQ_QUEUE_FORECAST = "/queue/gas.forecast"

# ── Paths ──────────────────────────────────────────────────────────────────────
MODELS_DIR = Path(os.environ.get("MODELS_DIR", r"C:\Temp\GasModel\models"))
LOG_DIR    = Path(os.environ.get("LOG_DIR",    r"C:\Python\DataEngineering\GasModel\logs"))
BACKFILL_YEARS       = int(os.environ.get("BACKFILL_YEARS", "3"))
MODEL_VERSIONS_KEEP  = int(os.environ.get("MODEL_VERSIONS_KEEP", "3"))

# HDD base temperature (°C) — standard for UK gas demand modelling
HDD_BASE = 15.5

# Features used for training and inference
FEATURE_COLS = ["hdd", "avg_wind_ms", "linepack", "day_of_week", "is_weekend", "month"]
TARGET_COL   = "demand_mcm"

# ── UK locations (must match C:\Python\Scrapes\gas\appsettings.py) ─────────────
LOCATIONS = {
    "london":     (51.5,  -0.1),
    "birmingham": (52.5,  -1.9),
    "manchester": (53.5,  -2.2),
    "leeds":      (53.8,  -1.5),
    "glasgow":    (55.9,  -4.3),
    "edinburgh":  (55.9,  -3.2),
    "cardiff":    (51.5,  -3.2),
    "belfast":    (54.6,  -5.9),
}
