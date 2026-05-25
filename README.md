# Gas Demand Model

A machine learning pipeline that trains multiple regression models on UK gas market data and generates daily 7-day demand forecasts, served through a real-time Dash dashboard.

---

## Architecture

```
backfill.py          ← One-time historical load (NGT API + Open-Meteo)
     │
     ▼
SQL Server (GAS_MODEL)
     │
     ▼
train.py             ← TrainPipeline: load → split → [tune] → fit → evaluate → save
     │                 Trains all models in MODELS registry
     ▼
C:\Temp\GasModel\models\   ← linear.pkl, gbm.pkl, rf.pkl
     │
     ▼
forecast.py          ← ForecastPipeline: load features → predict → persist → publish
     │                 Generates 7-day outlook for all loaded models
     ▼
GasForecast table + /queue/gas.forecast
     │                         │
     ▼                         ▼
dashboard/app.py       listener.py (daemon)
http://localhost:8050  Subscribes to gas.national, gas.entsog, gas.weather
                       Auto-triggers forecast.py on each new data arrival
```

---

## Injectable Pipeline Pattern

Both training and forecasting use the same injectable pattern as the scraper framework — swap any component without changing the entry point.

### Training

```python
TrainPipeline(
    loader=GasHistoricalLoader(),       # Where to load training data
    model=GBMDemandModel(),             # Which model to train
    evaluator=RegressionEvaluator(),    # How to measure performance
    engine=engine,
    models_dir=settings.MODELS_DIR,
    publish_handler=None,               # Optional: notify on completion
).run(
    feature_cols=settings.FEATURE_COLS,
    target_col=settings.TARGET_COL,
)
```

### Forecasting

```python
ForecastPipeline(
    loader=GasForecastLoader(days=7),   # Where to load forecast features
    models=loaded_models,               # Which trained models to use
    engine=engine,
    publish_handler=publish,            # Where to send results
).run(feature_cols=settings.FEATURE_COLS)
```

### Component contracts

| Component | Abstract base | Implement | Returns |
|-----------|--------------|-----------|---------|
| `DataLoader` | `models.loader.DataLoader` | `load(engine) -> pd.DataFrame` | Feature rows |
| `DemandModel` | `models.base.DemandModel` | `fit`, `predict`, `feature_importance`, `save`, `load` | Predictions |
| `Evaluator` | `models.evaluator.Evaluator` | `evaluate(name, y_true, y_pred) -> dict` | Metrics dict |
| `PublishHandler` | `Callable[[list[dict]], None]` | callable | — |

---

## Adding a New Model

**1. Create `models/my_model.py`:**

```python
import numpy as np
import joblib
from pathlib import Path
from models.base import DemandModel

class MyDemandModel(DemandModel):
    name = "my_model"                  # used as filename: my_model.pkl

    def __init__(self):
        self.model = ...               # any sklearn-compatible estimator

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self.model.fit(X, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)

    def feature_importance(self, feature_names: list[str]) -> dict:
        return dict(zip(feature_names, self.model.feature_importances_))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "MyDemandModel":
        return joblib.load(path)

    # Optional: define a search space to enable `python train.py --tune`
    def param_grid(self) -> dict:
        return {
            "n_estimators": [100, 200, 300],
            "max_depth":    [3, 4, 5],
        }
```

**2. Register in `models/__init__.py`:**

```python
from models.my_model import MyDemandModel

MODELS: list[type[DemandModel]] = [
    LinearDemandModel,
    GBMDemandModel,
    RandomForestDemandModel,
    MyDemandModel,          # ← add here
]
```

`train.py` and `forecast.py` pick it up automatically — no other changes needed.

---

## Adding a Custom Data Loader

To feed training or forecasting from a different source (e.g. a different database, an API):

```python
from models.loader import DataLoader
import pandas as pd
import sqlalchemy as sa

class MyForecastLoader(DataLoader):
    def __init__(self, days: int = 7):
        self.days = days

    def load(self, engine: sa.Engine) -> pd.DataFrame:
        # Must return a DataFrame with columns:
        # gas_date, hdd, avg_wind_ms, linepack, day_of_week, is_weekend, month
        # One row per forecast day.
        ...
```

Inject at call site:

```python
ForecastPipeline(loader=MyForecastLoader(days=7), ...).run(...)
```

---

## Adding a Custom Evaluator

```python
from models.evaluator import Evaluator
import numpy as np

class MyEvaluator(Evaluator):
    def evaluate(self, name: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict:
        return {
            "model":    name,
            "rmse_mcm": ...,
            "mae_mcm":  ...,
            "mape_pct": ...,
        }
```

---

## Features

| Feature | Description | Source |
|---------|-------------|--------|
| `hdd` | Heating Degree Days = max(0, 15.5 − avg_t2m) | Derived from weather |
| `avg_wind_ms` | Mean 10m wind speed across 8 UK cities | ECMWFForecast / Open-Meteo |
| `linepack` | Start-of-day linepack (mcm) | NationalGasData |
| `day_of_week` | 0 = Monday … 6 = Sunday | Derived from date |
| `is_weekend` | 1 if Saturday or Sunday | Derived from date |
| `month` | 1–12 for seasonal pattern | Derived from date |

**Target:** `demand_mcm` — NTS Actual Total Consumption (mcm/d)

---

## Registered Models

| Name | Class | MAPE | Description |
|------|-------|------|-------------|
| `linear` | `LinearDemandModel` | ~11% | Ridge regression (RidgeCV) with StandardScaler. Auto-selects L2 penalty via CV. |
| `gbm` | `GBMDemandModel` | ~7% | XGBoost (or LightGBM fallback). L1/L2 regularization. Captures non-linear HDD/wind interactions. |
| `rf` | `RandomForestDemandModel` | TBD | Random Forest. Robust to outliers, good uncertainty proxy via tree variance. |

---

## Weather Sources

| Scenario | Source | Table column |
|----------|--------|-------------|
| Training (historical) | Open-Meteo archive API | `step_hours = 0` |
| Live forecasting — GRIB2 pipeline running | ECMWF from `ECMWFForecast` | `step_hours > 0` |
| Live forecasting — no GRIB2 data | Open-Meteo forecast API (auto-fallback) | — |

`features.py` tries ECMWF from DB first; falls back to Open-Meteo automatically.

---

## Running Order

### First time only

```bash
# 1. Create GAS_MODEL database and tables (see Gas Scraper README for DDL)
#    Also create ModelEvaluation table:
#    CREATE TABLE [dbo].[ModelEvaluation] (model NVARCHAR(50), rmse_mcm FLOAT,
#      mae_mcm FLOAT, mape_pct FLOAT, trained_at NVARCHAR(50),
#      train_rows INT, test_rows INT);

# 2. Backfill 3 years of history
python backfill.py

# 3. Train all models
python train.py
```

### Every startup

```bash
# Start ActiveMQ
docker start activemq

# Start listener daemon (keep terminal open)
python listener.py

# Start dashboard (keep terminal open)
cd dashboard && python app.py
```

### Daily

```bash
# Run scrapers — listener auto-triggers forecast via MQ
python C:\Python\Scrapes\gas\main.py

# Or force a fresh 7-day forecast manually
python forecast.py
```

### Periodic retraining

```bash
python train.py           # retrain all registered models on latest data
python train.py --tune    # retrain with RandomizedSearchCV + TimeSeriesSplit (slower, better params)
```

---

## Dashboard

`http://localhost:8050` — auto-refreshes every 60 seconds.

| Panel | Description |
|-------|-------------|
| KPI cards | Latest D+1 forecast per model, active UMM count, forecast date |
| 7-Day Outlook | Demand curve for the next 7 days (all models) |
| Actuals vs Forecasts | 60-day history: actual, NGT forecast, model forecasts |
| Supply vs Demand | 30-day supply/demand balance bar chart |
| HDD vs Demand | Scatter with trend line — temperature-demand relationship |
| Model Evaluation | Latest RMSE / MAE / MAPE from most recent training run |
| Active UMMs | Current ENTSOG capacity restrictions |

---

## Database Tables

| Table | Key | Description |
|-------|-----|-------------|
| `NationalGasData` | `applicable_at`, `data_item` | Daily NGT metrics (demand, supply, linepack) |
| `ECMWFForecast` | `run_date`, `location`, `step_hours` | Weather per city per forecast step |
| `ENTSOGUrgentMarketMessages` | `id` | Active capacity restriction notices |
| `GasForecast` | `forecast_date`, `model_name` | 7-day demand forecasts (upserted each run) |
| `ModelEvaluation` | — | Training metrics appended on each retrain |

---

## Configuration (`appsettings.py`)

```python
DB_HOST        = "localhost"
DB_NAME        = "GAS_MODEL"
MODELS_DIR     = Path(r"C:\Temp\GasModel\models")
BACKFILL_YEARS = 3
HDD_BASE       = 15.5
FEATURE_COLS   = ["hdd", "avg_wind_ms", "linepack", "day_of_week", "is_weekend", "month"]
TARGET_COL     = "demand_mcm"
```
