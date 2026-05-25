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
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                reg_alpha=0.1,
                reg_lambda=1.0,
                random_state=42,
                verbosity=0,
            )
        else:
            self.model = _Base(
                n_estimators=300,
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
        self.model.fit(X, y)

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
