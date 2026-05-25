from abc import ABC, abstractmethod
import pandas as pd
import sqlalchemy as sa


class DataLoader(ABC):

    @abstractmethod
    def load(self, engine: sa.Engine) -> pd.DataFrame: ...


class GasHistoricalLoader(DataLoader):
    """Loads full historical feature matrix for training."""

    def load(self, engine: sa.Engine) -> pd.DataFrame:
        from features import build_features
        return build_features(engine)


class GasForecastLoader(DataLoader):
    """Loads feature rows for the next N days for inference."""

    def __init__(self, days: int = 7) -> None:
        self.days = days

    def load(self, engine: sa.Engine) -> pd.DataFrame:
        from features import forecast_features_multi_day
        return forecast_features_multi_day(engine, days=self.days)
