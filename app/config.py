from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTFORGE_", env_file=".env", extra="ignore")

    database_path: Path = Path("./data/agentforge.db")
    max_tasks: int = Field(default=8, ge=1, le=32)
    max_tool_calls: int = Field(default=12, ge=1, le=64)
    tool_timeout_seconds: float = Field(default=10, gt=0, le=300)
    run_timeout_seconds: float = Field(default=60, gt=0, le=3600)
    max_upload_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
    admin_token: str | None = None
    llm_provider: str = "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()
