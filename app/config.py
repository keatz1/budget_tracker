from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BT_", env_file=".env", extra="ignore")

    secret_key: str = "dev-only-change-me"
    database_path: Path = Path("data/budget.db")
    upload_dir: Path = Path("data/uploads")
    port: int = 8000
    session_days: int = 30
    currency_symbol: str = "$"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Settings()
