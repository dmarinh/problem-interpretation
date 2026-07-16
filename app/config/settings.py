"""
Application Configuration

Centralized configuration management using Pydantic Settings.
Loads from environment variables and .env files.
"""

from enum import Enum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Find project root by looking for .env or pyproject.toml
def find_project_root() -> Path:
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".env").exists() or (current / "pyproject.toml").exists():
            return current
        current = current.parent
    return Path.cwd()


PROJECT_ROOT = find_project_root()


# # Project root directory
# PROJECT_ROOT = Path(__file__).parent.parent


# =============================================================================
# ENUMS
# =============================================================================


class LogLevel(str, Enum):
    """Logging levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# =============================================================================
# SETTINGS
# =============================================================================


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application
    # -------------------------------------------------------------------------
    app_name: str = "Problem Interpretation Module"
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO

    # -------------------------------------------------------------------------
    # API Server
    # -------------------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000

    # -------------------------------------------------------------------------
    # LLM Configuration (model-agnostic via LiteLLM)
    # -------------------------------------------------------------------------
    llm_model: str = Field(
        default="gpt-4o",
        description="Model identifier (e.g., gpt-4o, claude-3-sonnet, ollama/llama2)",
    )
    llm_api_key: str | None = Field(
        default=None, description="API key for LLM provider"
    )
    llm_api_base: str | None = Field(
        default=None,
        description="Optional base URL override (for proxies or local models)",
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Generation temperature (lower = more deterministic)",
    )
    llm_max_tokens: int = Field(
        default=4096, ge=100, le=32000, description="Maximum tokens in response"
    )
    llm_instructor_mode: str | None = Field(
        default=None,
        description=(
            "Instructor extraction mode. "
            "None or 'TOOLS': native function/tool-calling API (best for OpenAI, Anthropic). "
            "'JSON': schema embedded in prompt (required for Ollama and other local models)."
        ),
    )

    # -------------------------------------------------------------------------
    # RAG Configuration
    # -------------------------------------------------------------------------
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model for embeddings",
    )
    vector_store_path: Path = Field(
        default=Path("./data/vector_store"),
        description="Path to ChromaDB persistent storage",
    )
    chunk_size: int = Field(
        default=512, ge=100, le=2000, description="Document chunk size for ingestion"
    )
    chunk_overlap: int = Field(
        default=50, ge=0, le=500, description="Overlap between chunks"
    )
    reranker_enabled: bool = Field(
        default=True,
        description="Enable cross-encoder reranking after initial vector search",
    )
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Sentence-transformers cross-encoder model for reranking",
    )

    # -------------------------------------------------------------------------
    # Retrieval Confidence Thresholds
    # -------------------------------------------------------------------------
    global_min_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Global minimum retrieval confidence threshold",
    )
    food_properties_confidence: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for food properties retrieval",
    )
    food_properties_fallback_confidence: float = Field(
        default=0.62,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence threshold for the per-field secondary retrieval tier used when the "
            "primary food-properties query misses threshold or returns a doc that lacks a field. "
            "Calibrated 2026-04-30 against 13 known-good food/property pairs (min score 0.6587) "
            "and 8 should-not-match cases (max score 0.5991); gap = 0.0596. 0.62 sits in the "
            "gap with ~0.04 margin on each side. Key validated cases: 'chicken' aw-fallback "
            "finds 'fresh poultry' doc at 0.7145 (Capture A target); 'poultry' ph/aw-fallback "
            "finds category docs at 0.6896/0.7584 (Capture B target). See §5.2 of specifications.md."
        ),
    )
    pathogen_hazards_confidence: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for pathogen hazards retrieval",
    )

    # -------------------------------------------------------------------------
    # Clarification Loop
    # -------------------------------------------------------------------------
    max_clarification_turns: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum clarification requests before applying defaults",
    )

    # -------------------------------------------------------------------------
    # Conservative Defaults (Safety-Critical)
    # -------------------------------------------------------------------------
    default_temperature_abuse_c: float = Field(
        default=25.0, description="Conservative ambient temperature assumption (°C)"
    )
    default_temperature_inactivation_conservative_c: float = Field(
        default=60.0,
        description=(
            "Conservative cooking temperature default (°C) when none is specified. "
            "Below typical pasteurization targets — conservative for thermal inactivation."
        ),
    )
    default_ph_neutral: float = Field(
        default=7.0, ge=0.0, le=14.0, description="Default pH when unknown"
    )
    default_water_activity: float = Field(
        default=0.99,
        ge=0.0,
        le=1.0,
        description="Default water activity when unknown (conservative = high)",
    )
    default_long_window_minutes: float = Field(
        default=10080.0,
        ge=1.0,
        description=(
            "Duration default (minutes) when no duration is specified in a single-step query. "
            "7 days (168 hours) — long enough for any model type's trajectory to reach the "
            "physical growth cap (±15 log CFU) under worst-case conditions."
        ),
    )

    # -------------------------------------------------------------------------
    # Engine Configuration (connection settings only, NOT constraints)
    # -------------------------------------------------------------------------
    combase_api_url: str | None = Field(
        default=None, description="ComBase API endpoint URL"
    )
    combase_timeout_seconds: int = Field(
        default=30, ge=5, le=120, description="Timeout for ComBase API calls"
    )

    # -------------------------------------------------------------------------
    # Constraint Cache Settings
    # -------------------------------------------------------------------------
    constraint_cache_ttl_seconds: int = Field(
        default=86400,
        ge=0,
        description="Time-to-live for cached engine constraints (0 = no expiry)",
    )
    constraint_cache_path: Path | None = Field(
        default=Path("./data/cache/constraints"),
        description="Path for persistent constraint cache (None = memory only)",
    )

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("vector_store_path", "constraint_cache_path", mode="before")
    @classmethod
    def ensure_path(cls, v) -> Path | None:
        """Ensure path fields are Path objects."""
        if v is None:
            return None
        return Path(v) if not isinstance(v, Path) else v


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

settings = Settings()
