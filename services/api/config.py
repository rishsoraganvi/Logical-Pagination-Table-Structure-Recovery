"""
Application configuration using pydantic-settings.
"""
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # --- Job storage ---
    DATA_DIR: Path = Field(default=Path("/data/jobs"))
    MAX_UPLOAD_MB: int = Field(default=500)

    # --- OCR worker ---
    OCR_WORKER_URL: str = Field(default="http://ocr-worker:8001")
    OCR_BATCH_SIZE: int = Field(default=16)
    OCR_TIMEOUT_SECONDS: int = Field(default=60)

    # --- TATR worker ---
    TATR_WORKER_URL: str = Field(default="http://tatr-worker:8002")
    TATR_TIMEOUT_SECONDS: int = Field(default=30)

    # --- Ollama (LLM) ---
    OLLAMA_BASE_URL: str = Field(default="http://ollama:11434")
    LLM_MODEL: str = Field(default="llama3.2:3b")
    VLM_MODEL: str = Field(default="qwen2-vl:7b")
    LLM_TIMEOUT_SECONDS: int = Field(default=60)
    VLM_ESCALATION_CAP: int = Field(default=20)  # Rule R-24

    # --- Fingerprinting ---
    HEADER_ZONE_FRACTION: float = Field(default=0.15)
    FOOTER_ZONE_FRACTION: float = Field(default=0.15)
    NEAR_BLANK_INK_THRESHOLD: float = Field(default=0.05)  # Rule R-10
    NATIVE_TEXT_CHAR_THRESHOLD: int = Field(default=30)  # Rule R-01

    # --- Boundary detection ---
    PELT_PENALTY: float = Field(default=3.0)  # Rule R-12, tunable
    SAME_TYPE_EMBED_SIMILARITY: float = Field(default=0.90)  # Threshold for same-type run grouping
    BOUNDARY_SIMILARITY_THRESHOLD: float = Field(default=0.45)  # Minimum sim for non-boundary (below = boundary)

    # --- Confidence ---
    LOW_CONFIDENCE_THRESHOLD: float = Field(default=0.70)  # Rule R-40

    # --- Redis ---
    REDIS_URL: str = Field(default="redis://redis:6379/0")
    JOB_TTL_SECONDS: int = Field(default=86400)  # 24h before Redis key expires

    # --- Rasterization ---
    OCR_DPI: int = Field(default=150)  # Rule R-02

    # --- Sentence transformer ---
    EMBED_MODEL: str = Field(default="all-MiniLM-L6-v2")
    EMBED_MODEL_CACHE: Path = Field(default=Path("/models/all-MiniLM-L6-v2"))

    # --- TATR ---
    TATR_MODEL: str = Field(default="microsoft/table-transformer-structure-recognition")
    TATR_MODEL_CACHE: Path = Field(default=Path("/models/tatr"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


# For backward compatibility
settings = get_settings()