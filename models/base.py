from abc import ABC, abstractmethod
from pathlib import Path
import numpy as np


class DemandModel(ABC):

    name: str  # subclasses must set this as a class attribute

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> None: ...

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray: ...

    @abstractmethod
    def feature_importance(self, feature_names: list[str]) -> dict: ...

    @abstractmethod
    def save(self, path: Path) -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: Path) -> "DemandModel": ...

    def param_grid(self) -> dict | None:
        """Return hyperparameter search space for RandomizedSearchCV, or None to skip tuning."""
        return None
