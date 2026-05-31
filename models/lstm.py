import logging
import numpy as np
import joblib
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from models.base import DemandModel

import torch
import torch.nn as nn


class _LSTMNet(nn.Module):
    """Two-layer LSTM with a linear output head."""

    def __init__(self, n_features: int, hidden_size: int, num_layers: int, dropout: float) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            n_features, hidden_size, num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])   # last timestep → demand prediction


class LSTMDemandModel(DemandModel):
    """
    LSTM neural network — learns sequential patterns across a SEQ_LEN-day window.
    Captures multi-day weather trends (e.g. a cold spell building over several days)
    that the single-day feature vector used by Ridge / GBM / RF cannot represent.

    Requires PyTorch:  pip install torch
    """

    name    = "lstm"
    SEQ_LEN = 14   # days of history per input sequence

    def __init__(
        self,
        hidden_size: int  = 64,
        num_layers:  int  = 2,
        dropout:     float = 0.2,
        epochs:      int  = 150,
        lr:          float = 1e-3,
        patience:    int  = 20,
    ) -> None:
        self.hidden_size = hidden_size
        self.num_layers  = num_layers
        self.dropout     = dropout
        self.epochs      = epochs
        self.lr          = lr
        self.patience    = patience
        self.scaler_X    = StandardScaler()
        self.scaler_y    = StandardScaler()
        self._net: _LSTMNet | None = None
        self._context: np.ndarray | None = None   # last SEQ_LEN scaled rows of training data

    # ── internal helpers ──────────────────────────────────────────────────────

    def _make_sequences(self, X_scaled: np.ndarray) -> np.ndarray:
        """(n, f) → (n - SEQ_LEN, SEQ_LEN, f) rolling windows."""
        return np.array([
            X_scaled[i - self.SEQ_LEN: i]
            for i in range(self.SEQ_LEN, len(X_scaled))
        ], dtype=np.float32)

    # ── DemandModel interface ─────────────────────────────────────────────────

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X_sc = self.scaler_X.fit_transform(X)
        y_sc = self.scaler_y.fit_transform(y.reshape(-1, 1)).ravel()

        self._context = X_sc[-self.SEQ_LEN:].copy()

        X_seq = self._make_sequences(X_sc)                # (n-SEQ_LEN, SEQ_LEN, f)
        y_seq = y_sc[self.SEQ_LEN:].astype(np.float32)   # aligned targets

        self._net = _LSTMNet(X.shape[1], self.hidden_size, self.num_layers, self.dropout)
        opt       = torch.optim.Adam(self._net.parameters(), lr=self.lr)
        loss_fn   = nn.MSELoss()

        X_t = torch.from_numpy(X_seq)
        y_t = torch.from_numpy(y_seq).unsqueeze(1)

        best_loss, wait = float("inf"), 0
        self._net.train()
        for epoch in range(1, self.epochs + 1):
            opt.zero_grad()
            loss = loss_fn(self._net(X_t), y_t)
            loss.backward()
            opt.step()

            val = loss.item()
            if val < best_loss - 1e-5:
                best_loss, wait = val, 0
            else:
                wait += 1
                if wait >= self.patience:
                    logging.info("[lstm] early stop at epoch %d  loss=%.4f", epoch, val)
                    break

            if epoch % 25 == 0:
                logging.info("[lstm] epoch %d/%d  loss=%.4f", epoch, self.epochs, val)

    def predict(self, X: np.ndarray) -> np.ndarray:
        X_sc = self.scaler_X.transform(X)
        # Prepend stored training context so first prediction has full SEQ_LEN history
        full = np.vstack([self._context, X_sc]).astype(np.float32)
        seqs = self._make_sequences(full)   # gives exactly len(X) sequences

        self._net.eval()
        with torch.no_grad():
            preds_sc = self._net(torch.from_numpy(seqs)).numpy().ravel()

        return self.scaler_y.inverse_transform(preds_sc.reshape(-1, 1)).ravel()

    def feature_importance(self, feature_names: list[str]) -> dict:
        # LSTMs don't have native feature importance
        return {f: 0.0 for f in feature_names}

    def param_grid(self) -> None:
        # sklearn RandomizedSearchCV doesn't support PyTorch natively;
        # tune by adjusting __init__ params and comparing CV-RMSE in logs
        return None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @classmethod
    def load(cls, path: Path) -> "LSTMDemandModel":
        return joblib.load(path)
