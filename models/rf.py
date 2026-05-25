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
