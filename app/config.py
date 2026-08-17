from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://listenery:listenery@localhost:5432/listenery"
    redis_url: str = "redis://localhost:6379/0"
    dispatch_poll_interval_seconds: int = 10

    class Config:
        env_file = ".env"


settings = Settings()
