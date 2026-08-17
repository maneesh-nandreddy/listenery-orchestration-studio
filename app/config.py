from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://listenery:listenery@localhost:5432/listenery"
    redis_url: str = "redis://localhost:6379/0"
    dispatch_poll_interval_seconds: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()
