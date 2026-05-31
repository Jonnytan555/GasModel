import numpy as np
import joblib
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from models.base import DemandModel


class RandomForestDemandModel(DemandModel):

    name = "rf"

    def __init__(self) -> None:
        self.model = RandomForestRegressor(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=5,
            max_features=0.7,
            random_state=42,
            n_jobs=-1,
        )

    def param_grid(self) -> dict:
        return {
            "n_estimators":    [200, 300, 500],
            "max_depth":       [4, 6, 8, 10, None],
            "min_samples_leaf":[2, 5, 10, 20],
            "max_features":    [0.5, 0.7, 1.0, "sqrt"],
        }

    def optuna_space(self, trial) -> dict:
        return {
            "n_estimators":     trial.suggest_int("n_estimators", 100, 600),
            "max_depth":        trial.suggest_int("max_depth", 3, 15),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 2, 20),
            "max_features":     trial.suggest_float("max_features", 0.3, 1.0),
        }

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
    def load(cls, path: Path) -> "RandomForestDemandModel":
        return joblib.load(path)
