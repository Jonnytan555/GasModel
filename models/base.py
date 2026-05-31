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
    def save(self, path: "Path | str") -> None: ...

    @classmethod
    @abstractmethod
    def load(cls, path: "Path | str") -> "DemandModel": ...

    def param_grid(self) -> dict | None:
        """Return hyperparameter search space for RandomizedSearchCV fallback, or None to skip tuning."""
        return None

    def optuna_space(self, trial) -> dict | None:
        """Return hyperparameters sampled from an Optuna trial, or None to skip Optuna tuning."""
        return None
