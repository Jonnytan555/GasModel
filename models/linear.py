import numpy as np
import joblib
from pathlib import Path
from sklearn.linear_model import RidgeCV
from sklearn.preprocessing import StandardScaler
from models.base import DemandModel


class LinearDemandModel(DemandModel):
    """
    Ridge regression with standard scaling.
    RidgeCV selects the L2 penalty alpha via internal cross-validation —
    prevents coefficient blow-up when HDD/temperature features are correlated.
    """

    name = "linear"

    def __init__(self):
        self.scaler = StandardScaler()
        self.model  = RidgeCV(alphas=[0.01, 0.1, 1.0, 10.0, 100.0], cv=5)

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, y)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(self.scaler.transform(X))

    def feature_importance(self, feature_names: list[str]) -> dict:
        return dict(zip(feature_names, self.model.coef_))

    # RidgeCV handles regularization internally — no external grid search needed
    def param_grid(self) -> None:
        return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "LinearDemandModel":
        return joblib.load(path)
