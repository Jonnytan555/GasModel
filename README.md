# UK Gas Demand Forecasting Pipeline

A machine learning system that forecasts UK daily natural gas demand up to 7 days ahead. It pulls live data from public APIs, trains three regression models on 3 years of history, and serves a real-time dashboard showing the forecast alongside actuals, supply, and weather context.

---

## What problem does this solve?

UK gas demand varies enormously day to day — from ~100 mcm/d in summer to ~450 mcm/d in a cold winter snap. The primary driver is temperature: when it gets cold, residential and commercial heating demand spikes. Wind speed matters too, because wind turbines displace gas-fired power generation.

Being able to forecast demand 7 days ahead is useful for:
- Gas traders and shippers planning their positions
- Grid operators managing linepack and supply nominations
- Anyone who wants to understand the relationship between weather and energy demand

The system forecasts **NTS Actual Total Consumption** (mcm/d) — the total gas consumed on the UK National Transmission System each day.

---

## Where does the data come from?

The pipeline collects from three public sources, each refreshed hourly by a companion scraper project (`C:\Python\Scrapes\gas`):

### 1. National Gas Transmission (NGT) API
The public API at `api.nationalgas.com` publishes daily operational data for the UK gas grid. We collect:
- **Actual demand** (`demand_mcm`) — what was actually consumed each day. This is our training target.
- **NGT's own demand forecast** — used as a benchmark to compare our models against
- **Total supply** — gas entering the NTS from all sources
- **Opening linepack** — the amount of gas stored in the pipeline network at the start of the gas day. A proxy for system stress.

### 2. ENTSOG Transparency Platform
The European Network of Transmission System Operators publishes **Urgent Market Messages (UMMs)** — notices of unplanned outages or capacity restrictions at interconnectors and terminals. These affect supply-side availability and are shown on the dashboard.

### 3. Weather (Open-Meteo / ECMWF)
Weather data for 8 UK cities (London, Birmingham, Manchester, Leeds, Glasgow, Edinburgh, Cardiff, Belfast). For training we use Open-Meteo's historical archive. For live forecasting we use ECMWF GRIB2 forecast files if available, with Open-Meteo as an automatic fallback.

---

## Why these 6 features?

Gas demand in the UK is well-studied. The six features we use account for the vast majority of day-to-day variation:

| Feature | Why it matters |
|---------|---------------|
| `hdd` | **Heating Degree Days** = max(0, 15.5 − avg_temperature). The single strongest predictor — below 15.5°C, every degree colder adds roughly proportional heating demand. The 15.5°C base is the UK industry standard. |
| `avg_wind_ms` | Higher wind means more wind power generation, which displaces gas-fired power stations. A 5 m/s increase in wind can reduce gas demand by 15–20 mcm/d. |
| `linepack` | Opening linepack captures how much "buffer" is in the system. Low linepack days often coincide with high-demand periods and constrain supply flexibility. |
| `day_of_week` | Weekday demand is higher than weekends due to industrial and commercial activity. |
| `is_weekend` | A cleaner binary version of the weekend effect, used alongside day_of_week. |
| `month` | Captures seasonal patterns beyond what HDD picks up — gas day length, holiday periods, seasonal industrial load. |

**Target variable:** `demand_mcm` — NTS Actual Total Consumption in million cubic metres per day.

---

## The models

We train three models on the same data and run all three at forecast time. This gives us a range of predictions and lets us compare approaches.

### Model 1 — Ridge Regression (`linear`)
A linear model with L2 regularisation. The simplest of the three — it assumes demand is a weighted sum of the features. The `RidgeCV` variant automatically selects the regularisation strength via cross-validation, which prevents any single feature's coefficient from growing unrealistically large.

**Good for:** Interpretability — you can read off the coefficients and understand exactly how much each degree of HDD is worth in mcm/d. Acts as a sanity-check baseline.

**Limitation:** Can't capture interactions between features (e.g. the effect of cold *and* low wind together is worse than either alone).

### Model 2 — Gradient Boosting (`gbm`)
An ensemble of decision trees built sequentially, where each tree corrects the residual errors of the previous one. Uses XGBoost (with LightGBM as a fallback). L1 and L2 regularisation terms prevent the trees from memorising noise.

**Good for:** Non-linear interactions — it naturally captures things like "demand spikes disproportionately when HDD > 10 *and* wind is low simultaneously." Typically achieves the lowest forecast error (~7% MAPE).

**Limitation:** Less interpretable than Ridge. Can overfit if not regularised.

### Model 3 — Random Forest (`rf`)
An ensemble of independent decision trees, each trained on a random subset of the data and features. The final prediction is the average across all trees.

**Good for:** Robustness — outlier days (unexpected cold snaps, bank holidays) affect individual trees but not the ensemble. The spread of tree predictions also gives a rough uncertainty estimate.

**Limitation:** Tends to underperform GBM on structured tabular data but provides useful ensemble diversity.

---

## How it all connects — the pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1 — Backfill (run once)                                   │
│  backfill.py pulls 3 years of NGT data + weather history        │
│  and writes it to SQL Server                                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2 — Feature Engineering                                   │
│  features.py joins NGT demand data with weather, calculates     │
│  HDD, day flags, and writes one row per gas day                 │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3 — Training (run once, then periodically)                │
│  train.py loads the feature table, splits 80% train / 20% test  │
│  (chronologically), fits all 3 models, evaluates on the test    │
│  window, and saves each model as a .pkl file                    │
│                                                                 │
│  Optional: python train.py --tune                               │
│  Runs RandomizedSearchCV with TimeSeriesSplit (5-fold) to find  │
│  optimal hyperparameters before the final fit                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4 — Live pipeline (runs continuously)                     │
│                                                                 │
│  Scrapers run hourly via Airflow and publish to ActiveMQ:       │
│    /queue/gas.national  ←  NGT data                             │
│    /queue/gas.entsog    ←  ENTSOG UMMs                          │
│    /queue/gas.weather   ←  Weather data                         │
│                                  │                              │
│  listener.py subscribes to all three queues.                    │
│  On any new message → loads latest weather features →           │
│  runs all 3 models → writes 7-day forecast to GasForecast       │
│  table → publishes to /queue/gas.forecast                       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 5 — Dashboard                                             │
│  dashboard/app.py reads from SQL Server and refreshes every     │
│  60 seconds. Shows the 7-day forecast, actuals vs forecasts,   │
│  supply/demand balance, and model evaluation metrics.           │
│  http://localhost:8050                                          │
└─────────────────────────────────────────────────────────────────┘
```

### Why ActiveMQ?

The scraper and the model are completely decoupled. The scraper doesn't know or care that a forecasting model exists — it just publishes "new data is available" to a queue. The listener doesn't know where the data came from — it just wakes up, reads the database, and runs the forecast. This means either side can be restarted, updated, or replaced independently.

### Why train/test split chronologically?

Standard k-fold cross-validation shuffles data randomly, which would mean the model sees future data during training — an unrealistic advantage. We always split time-series data so the test window is strictly after the training window. When using `--tune`, we use `TimeSeriesSplit` which applies the same principle across 5 rolling windows.

---

## Getting started

### Prerequisites

- Python 3.11+
- SQL Server with an empty `GAS_MODEL` database
- Docker Desktop (for ActiveMQ and the full stack)

Install dependencies:
```bash
pip install -r requirements.txt
```

---

### Step 1 — Create the database tables

Run this SQL in your `GAS_MODEL` database:

```sql
CREATE TABLE [dbo].[ModelEvaluation] (
    model           NVARCHAR(50),
    rmse_mcm        FLOAT,
    mae_mcm         FLOAT,
    mape_pct        FLOAT,
    train_rmse_mcm  FLOAT,
    cv_rmse_mcm     FLOAT,
    cv_rmse_std     FLOAT,
    trained_at      NVARCHAR(50),
    train_rows      INT,
    test_rows       INT
);
```

If you already have this table, run:
```sql
ALTER TABLE [dbo].[ModelEvaluation] ADD train_rmse_mcm FLOAT;
ALTER TABLE [dbo].[ModelEvaluation] ADD cv_rmse_mcm    FLOAT;
ALTER TABLE [dbo].[ModelEvaluation] ADD cv_rmse_std    FLOAT;
```

The other tables (`NationalGasData`, `ECMWFForecast`, `GasForecast`, `ENTSOGUrgentMarketMessages`) are created automatically by the scraper on first run.

---

### Step 2 — Backfill 3 years of history

This pulls historical demand and weather data from the public APIs and populates the database. Takes 5–10 minutes.

```bash
python backfill.py
```

You should see log lines like:
```
[backfill] Fetching NGT data from 2023-01-01 to 2026-05-26...
[backfill] Inserted 1096 rows into NationalGasData
[backfill] Fetching weather for london 2023-01-01 → 2026-05-26...
```

---

### Step 3 — Train the models

```bash
python train.py
```

This loads the feature table, trains Ridge, GBM, and Random Forest, evaluates each on the held-out test window, and saves `.pkl` files to `MODELS_DIR`. At the end you'll see a summary:

```
======================================================
Model         RMSE (mcm)   MAE (mcm)   MAPE (%)
------------------------------------------------------
linear             28.41       21.33       11.2
gbm                14.87       11.05        7.1
rf                 17.23       12.88        8.4
======================================================
```

To also search for better hyperparameters (takes 15–30 minutes):
```bash
python train.py --tune
```

---

### Step 4 — Start the listener

The listener is a long-running process that wakes up whenever new data arrives via ActiveMQ and runs a fresh 7-day forecast.

```bash
# Start ActiveMQ first (if not using Docker)
docker run -d -p 61613:61613 -p 8161:8161 apache/activemq-classic:5.18.3

# Then start the listener (keep this terminal open)
python listener.py
```

You'll see:
```
[listener] Subscribed to /queue/gas.national
[listener] Subscribed to /queue/gas.entsog
[listener] Subscribed to /queue/gas.weather
[listener] Waiting for data  (Ctrl+C to stop)
```

---

### Step 5 — Start the dashboard

```bash
python dashboard/app.py
```

Open `http://localhost:8050` in your browser.

---

### Step 6 — Run the scrapers

```bash
python C:\Python\Scrapes\gas\main.py
```

This triggers a full scrape of NGT and ENTSOG, writes the results to SQL Server, and publishes to ActiveMQ. The listener will wake up automatically and run the forecast.

---

## Running everything with Docker

The `docker-compose.yml` starts the full stack in one command:

```bash
# First time only
docker compose up airflow-init
docker compose run --rm gas-model python backfill.py
docker compose run --rm gas-model python train.py

# Every startup
docker compose up -d
```

| Service | What it runs | URL |
|---------|-------------|-----|
| `airflow-web` | Airflow UI — triggers and monitors scraper DAG | `http://localhost:8080` |
| `airflow-sch` | Runs the gas scraper DAG hourly | — |
| `activemq` | Message broker | `http://localhost:8161` |
| `gas-listener` | Forecast daemon | — |
| `gas-dashboard` | Dash dashboard | `http://localhost:8050` |

---

## Dashboard panels

| Panel | What it shows |
|-------|---------------|
| KPI cards | D+1 forecast per model, active UMM count, last forecast time |
| 7-Day Outlook | Demand forecast for the next 7 days — one line per model |
| Actuals vs Forecasts | 60-day history comparing actual demand, NGT's own forecast, and our model forecasts |
| Supply vs Demand | 30-day bar chart of supply vs demand balance |
| HDD vs Demand | Scatter plot showing the temperature–demand relationship with trend line |
| Model Evaluation | RMSE / MAE / MAPE from the most recent training run |
| Active UMMs | Current ENTSOG capacity restriction notices |

---

## Model performance metrics explained

- **RMSE (Root Mean Squared Error)** — average forecast error in mcm/d, penalising large misses more heavily. Lower is better.
- **MAE (Mean Absolute Error)** — average absolute forecast error in mcm/d. More interpretable than RMSE. A MAE of 11 mcm means we're typically off by 11 mcm/d.
- **MAPE (Mean Absolute Percentage Error)** — average error as a percentage of actual demand. Easier to compare across seasons. A MAPE of 7% means we're typically within 7% of actual demand.

---

## Configuration

All settings are in `appsettings.py` and can be overridden with environment variables:

| Setting | Env var | Default | Description |
|---------|---------|---------|-------------|
| SQL Server host | `DB_HOST` | `localhost` | Database server |
| Database name | `DB_NAME` | `GAS_MODEL` | Target database |
| ActiveMQ host | `MQ_HOST` | `localhost` | Message broker |
| Models directory | `MODELS_DIR` | `C:\Temp\GasModel\models` | Where `.pkl` files are saved |
| Log directory | `LOG_DIR` | `C:\Python\DataEngineering\GasModel\logs` | Where log files are written |
| Backfill years | `BACKFILL_YEARS` | `3` | How many years of history to load |
| HDD base temp | — | `15.5°C` | UK industry standard base temperature |

---

## Project structure

```
GasModel/
├── appsettings.py        Configuration and environment variables
├── backfill.py           One-time historical data load
├── train.py              Train all registered models
├── forecast.py           Run a one-off 7-day forecast
├── listener.py           ActiveMQ daemon — auto-triggers forecasts
├── features.py           Feature engineering (HDD, joins, etc.)
├── db.py                 SQLAlchemy engine factory
├── models/
│   ├── base.py           Abstract DemandModel interface
│   ├── linear.py         Ridge regression model
│   ├── gbm.py            Gradient boosting model (XGBoost / LightGBM)
│   ├── rf.py             Random Forest model
│   ├── pipeline.py       TrainPipeline and ForecastPipeline orchestrators
│   ├── loader.py         DataLoader implementations
│   ├── evaluator.py      RegressionEvaluator (RMSE, MAE, MAPE)
│   └── __init__.py       MODELS registry
├── dashboard/
│   ├── app.py            Dash application
│   └── data.py           Dashboard data queries
├── Dockerfile            Container image for listener / dashboard / train
└── docker-compose.yml    Full stack (Airflow, ActiveMQ, listener, dashboard)
```

---

## Extending the pipeline

### Adding a new model

Create `models/my_model.py` implementing the `DemandModel` interface, then register it in `models/__init__.py`. `train.py` and `forecast.py` pick it up automatically — no other changes needed. See the existing models for reference.

### Adding a new data source

Implement a `DataLoader` subclass and pass it to `TrainPipeline` or `ForecastPipeline`. The pipeline only cares that `load(engine)` returns a DataFrame with the expected feature columns.
