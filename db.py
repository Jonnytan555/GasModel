import sqlalchemy as sa
import appsettings as settings


def get_engine() -> sa.Engine:
    return sa.create_engine(
        f"mssql+pyodbc://{settings.DB_HOST}/{settings.DB_NAME}"
        f"?driver={settings.DB_DRIVER.replace(' ', '+')}"
    )
