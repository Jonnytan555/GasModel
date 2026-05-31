"""
train.py — Train all registered models on historical data.

Run:
  python train.py           # train with default params
  python train.py --tune    # tune hyperparameters (Optuna if installed, else RandomizedSearchCV)

Optuna uses Bayesian optimisation (TPE sampler) with MedianPruner to find better
hyperparameters than random search in the same number of trials.  Install with:
  pip install optuna
"""

import os
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import appsettings as settings
import logger
logger.setup_log(
    app="gas_train",
    filename=str(settings.LOG_DIR / "gas_train.log"),
    use_stream=True,
)
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

    logging.info("=" * 80)
    logging.info("%-12s  %10s  %10s  %10s  %8s  %14s",
                 "Model", "train-RMSE", "test-RMSE", "gap", "MAPE (%)", "CV-RMSE ± std")
    logging.info("-" * 80)
    for r in results:
        gap      = r["rmse_mcm"] - r["train_rmse_mcm"]
        flag     = "  ***" if gap > r["rmse_mcm"] * 0.5 else ""
        cv_str   = f"{r['cv_rmse_mcm']:.2f} ± {r['cv_rmse_std']:.2f}"
        logging.info("%-12s  %10.2f  %10.2f  %+10.2f  %8.1f  %14s%s",
                     r["model"], r["train_rmse_mcm"], r["rmse_mcm"],
                     gap, r["mape_pct"], cv_str, flag)
    logging.info("=" * 80)
    logging.info("*** = train/test gap > 50%% of test RMSE — possible overfit")
    logging.info("Training complete.")
