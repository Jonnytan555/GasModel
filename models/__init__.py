from models.base import DemandModel
from models.linear import LinearDemandModel
from models.gbm import GBMDemandModel
from models.rf import RandomForestDemandModel

# Register all models here — TrainPipeline and ForecastPipeline iterate this list
MODELS: list[type[DemandModel]] = [
    LinearDemandModel,
    GBMDemandModel,
    RandomForestDemandModel,
]
