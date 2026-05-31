from models.base import DemandModel
from models.linear import LinearDemandModel
from models.gbm import GBMDemandModel
from models.rf import RandomForestDemandModel

# LSTM is optional — requires PyTorch (pip install torch)
try:
    from models.lstm import LSTMDemandModel
    _LSTM_AVAILABLE = True
except ImportError:
    _LSTM_AVAILABLE = False

# Register all models here — TrainPipeline and ForecastPipeline iterate this list
MODELS: list[type[DemandModel]] = [
    LinearDemandModel,
    GBMDemandModel,
    RandomForestDemandModel,
] + ([LSTMDemandModel] if _LSTM_AVAILABLE else [])
