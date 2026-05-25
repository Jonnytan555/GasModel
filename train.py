"""
train.py — Train all registered models on historical data.

Run:
  python train.py           # train with default params
  python train.py --tune    # tune hyperparameters first (slower, better results)
"""

import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logger
logger.setup_log(
    app="gas_train",
    filename=os.path.join(r"C:\Python\DataEngineering\GasModel\logs", "gas_train.log"),
    use_stream=True,
)

import appsettings as settings
from db import get_engine
from models import MODELS
from models.loader import GasHistoricalLoader
from models.evaluator import RegressionEvaluator
from models.pipeline import TrainPipeline


if __name__ == "__main__":
    tune    = "--tune" in sys.argv
    engine  = get_engine()
    results = []

    if tune:
        logging.info("Hyperparameter tuning enabled (RandomizedSearchCV + TimeSeriesSplit)")

    for Model in MODELS:
        result = TrainPipeline(
            loader=GasHistoricalLoader(),
            model=Model(),
            evaluator=RegressionEvaluator(),
            engine=engine,
            models_dir=settings.MODELS_DIR,
            versions_to_keep=settings.MODEL_VERSIONS_KEEP,
            tune=tune,
        ).run(
            feature_cols=settings.FEATURE_COLS,
            target_col=settings.TARGET_COL,
        )
        results.append(result)

    logging.info("=" * 54)
    logging.info("%-12s  %10s  %10s  %8s", "Model", "RMSE (mcm)", "MAE (mcm)", "MAPE (%)")
    logging.info("-" * 54)
    for r in results:
        logging.info("%-12s  %10.2f  %10.2f  %8.1f",
                     r["model"], r["rmse_mcm"], r["mae_mcm"], r["mape_pct"])
    logging.info("=" * 54)
    logging.info("Training complete.")
