"""
Smoke tests — no database, no ActiveMQ, no S3.
Verify models can fit and predict on in-memory data.
"""
import numpy as np
import pytest
from pathlib import Path


N_ROWS     = 200
N_FEATURES = 6
RNG        = np.random.default_rng(42)

@pytest.fixture
def xy():
    X = RNG.random((N_ROWS, N_FEATURES)).astype(np.float32)
    y = (X[:, 0] * 300 + RNG.random(N_ROWS) * 20).astype(np.float32)
    return X, y


def test_linear_fit_predict(xy):
    from models.linear import LinearDemandModel
    X, y = xy
    m = LinearDemandModel()
    m.fit(X, y)
    preds = m.predict(X[:5])
    assert preds.shape == (5,)
    assert not np.any(np.isnan(preds))


def test_gbm_fit_predict(xy):
    from models.gbm import GBMDemandModel
    X, y = xy
    m = GBMDemandModel()
    m.fit(X, y)
    preds = m.predict(X[:5])
    assert preds.shape == (5,)
    assert not np.any(np.isnan(preds))


def test_rf_fit_predict(xy):
    from models.rf import RandomForestDemandModel
    X, y = xy
    m = RandomForestDemandModel()
    m.fit(X, y)
    preds = m.predict(X[:5])
    assert preds.shape == (5,)
    assert not np.any(np.isnan(preds))


def test_lstm_fit_predict(xy):
    pytest.importorskip("torch")
    from models.lstm import LSTMDemandModel
    X, y = xy
    m = LSTMDemandModel(hidden_size=16, num_layers=1, epochs=5)
    m.fit(X, y)
    preds = m.predict(X[:5])
    assert preds.shape == (5,)
    assert not np.any(np.isnan(preds))


def test_feature_importance(xy):
    from models.linear import LinearDemandModel
    X, y = xy
    feature_names = ["hdd", "avg_wind_ms", "linepack", "day_of_week", "is_weekend", "month"]
    m = LinearDemandModel()
    m.fit(X, y)
    imp = m.feature_importance(feature_names)
    assert set(imp.keys()) == set(feature_names)


def test_local_save_load(xy, tmp_path):
    from models.linear import LinearDemandModel
    from models.storage import model_exists
    X, y = xy
    m = LinearDemandModel()
    m.fit(X, y)
    path = tmp_path / "linear.pkl"
    m.save(path)
    assert model_exists(path)
    loaded = LinearDemandModel.load(path)
    np.testing.assert_allclose(m.predict(X[:5]), loaded.predict(X[:5]))


def test_param_grid_defined():
    from models.gbm import GBMDemandModel
    from models.rf import RandomForestDemandModel
    from models.linear import LinearDemandModel
    assert GBMDemandModel().param_grid() is not None
    assert RandomForestDemandModel().param_grid() is not None
    assert LinearDemandModel().param_grid() is None   # RidgeCV handles tuning internally


def test_models_registry():
    from models import MODELS
    names = [m.name for m in MODELS]
    assert "linear" in names
    assert "gbm" in names
    assert "rf" in names
