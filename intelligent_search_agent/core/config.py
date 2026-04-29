import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from intelligent_search_agent.core.pricing import pricing_for

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE_PATH = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE_PATH)


def apply_openai_environment(settings: "Settings") -> None:
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_base_url:
        os.environ["OPENAI_BASE_URL"] = settings.openai_base_url
    else:
        os.environ.pop("OPENAI_BASE_URL", None)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    environment: str = "dev"
    log_level: str = "INFO"
    api_title: str = "Intelligent Search Agent"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    admin_api_key: str | None = None
    enable_admin_api: bool = True
    persist_chat_sessions: bool = True
    llm_rerank_enabled: bool = True
    llm_rerank_top_k: int = 12
    allowed_source_url_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "commons.wikimedia.org",
            "upload.wikimedia.org",
            "journalbelgianhistory.be",
            "www.journalbelgianhistory.be",
        ]
    )

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "intelligent_search_agent"
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_sslmode: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None

    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    rag_top_k: int = 10
    rag_candidate_k: int = 200
    rag_min_similarity: float = 0.30
    rag_hybrid_alpha: float = 0.70
    agent_request_limit: int = 8

    asset_storage_backend: Literal["local", "network", "http", "s3", "minio"] = "local"
    asset_root: Path = Field(default=PROJECT_ROOT / "storage" / "assets")

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or value == "":
            return ["*"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("allowed_source_url_hosts", mode="before")
    @classmethod
    def parse_allowed_source_url_hosts(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @field_validator("asset_root", mode="before")
    @classmethod
    def resolve_asset_root(cls, value):
        path = Path(value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @computed_field
    @property
    def pydantic_ai_model_string(self) -> str:
        return f"openai:{self.openai_model}"

    @computed_field
    @property
    def model_input_cost_per_token(self) -> float:
        return float(pricing_for(self.openai_model)["input_per_million"]) / 1_000_000

    @computed_field
    @property
    def model_output_cost_per_token(self) -> float:
        return float(pricing_for(self.openai_model)["output_per_million"]) / 1_000_000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    apply_openai_environment(settings)
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    load_dotenv(ENV_FILE_PATH, override=True)
    return get_settings()
