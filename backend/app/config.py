"""Application settings loaded from environment via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM ---
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")
    anthropic_model_primary: str = "claude-sonnet-4-6"
    anthropic_model_fast: str = "claude-haiku-4-5-20251001"
    gemini_model: str = "gemini-2.5-pro"

    # --- Embeddings ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # --- Postgres ---
    database_url: str = (
        "postgresql+asyncpg://compliance:compliance@postgres:5432/compliance"
    )

    # --- Chroma ---
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_collection: str = "regulatory_docs"

    # --- Backend ---
    backend_host: str = "0.0.0.0"
    backend_port: int = 8080
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Rate limit / token budget ---
    llm_rate_limit_rpm: int = 60
    llm_token_budget_per_request: int = 200_000
    llm_token_budget_per_day: int = 2_000_000

    # --- MCP ---
    mcp_transport: str = "streamable-http"
    mcp_control_registry_port: int = 9001
    mcp_document_store_port: int = 9002

    # --- A2A ---
    a2a_public_base_url: str = "http://localhost:8080"
    a2a_agent_name: str = "extraction-agent"

    # --- paths ---
    repo_root: Path = Path(__file__).resolve().parents[1]
    prompts_dir: Path = Path(__file__).resolve().parents[1] / "prompts"
    uploads_dir: Path = Path("/app/uploads")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
