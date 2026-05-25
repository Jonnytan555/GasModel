from abc import ABC, abstractmethod
import numpy as np


class Evaluator(ABC):

    @abstractmethod
    def evaluate(self, name: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict: ...


class RegressionEvaluator(Evaluator):

    def evaluate(self, name: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict:
        rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
        mae  = float(np.mean(np.abs(y_true - y_pred)))
        mape = float(np.mean(np.abs((y_true - y_pred) / np.where(y_true != 0, y_true, 1)))) * 100
        return {
            "model":    name,
            "rmse_mcm": round(rmse, 2),
            "mae_mcm":  round(mae, 2),
            "mape_pct": round(mape, 1),
        }
