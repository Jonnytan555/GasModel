import numpy as np
import joblib
from pathlib import Path
from models.base import DemandModel

try:
    from xgboost import XGBRegressor as _Base
    _BACKEND = "xgboost"
except ImportError:
    from lightgbm import LGBMRegressor as _Base
    _BACKEND = "lightgbm"


class GBMDemandModel(DemandModel):
    """
    Gradient boosting model — captures non-linear interactions that linear
    regression misses (e.g. cold snaps, wind + temperature combined effects).

    Uses XGBoost if installed, falls back to LightGBM.
    reg_alpha (L1) and reg_lambda (L2) shrink weak tree contributions.
    """

    name = "gbm"

    def __init__(self):
        if _BACKEND == "xgboost":
            self.model = _Base(
                n_estimators=1000,       # upper bound — early stopping decides true count
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=1.0,
                early_stopping_rounds=50,
                random_state=42,
                verbosity=0,
            )
        else:
            self.model = _Base(
                n_estimators=1000,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=1.0,
                random_state=42,
                verbose=-1,
            )

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        split = int(len(X) * 0.85)
        if _BACKEND == "xgboost":
            self.model.fit(
                X[:split], y[:split],
                eval_set=[(X[split:], y[split:])],
                verbose=False,
            )
        else:
            import lightgbm as lgb
            self.model.fit(
                X[:split], y[:split],
                eval_set=[(X[split:], y[split:])],
                callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
            )

    def param_grid(self) -> dict:
        return {
            "n_estimators":    [200, 300, 500],
            "max_depth":       [3, 4, 5, 6],
            "learning_rate":   [0.01, 0.05, 0.1],
            "subsample":       [0.7, 0.8, 0.9],
            "colsample_bytree":[0.7, 0.8, 1.0],
            "reg_alpha":       [0, 0.01, 0.1, 1.0],
            "reg_lambda":      [0.5, 1.0, 2.0, 5.0],
        }

    def optuna_space(self, trial) -> dict:
        # n_estimators excluded — early stopping determines true tree count
        return {
            "max_depth":        trial.suggest_int("max_depth", 3, 6),
            "learning_rate":    trial.suggest_float("learning_rate", 0.005, 0.2, log=True),
            "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha":        trial.suggest_float("reg_alpha", 1e-3, 2.0, log=True),
            "reg_lambda":       trial.suggest_float("reg_lambda", 0.1, 5.0, log=True),
        }

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)

    def feature_importance(self, feature_names: list[str]) -> dict:
        return dict(zip(feature_names, self.model.feature_importances_))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "GBMDemandModel":
        return joblib.load(path)
