"""
Application Configuration

Centralized configuration management using Pydantic Settings.
Loads from environment variables and .env files.
"""

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent


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
        default="gpt-4-turbo-preview",
        description="Model identifier (e.g., gpt-4-turbo-preview, claude-3-sonnet, ollama/llama2)"
    )
    llm_api_key: Optional[str] = Field(
        default=None,
        description="API key for LLM provider"
    )
    llm_api_base: Optional[str] = Field(
        default=None,
        description="Optional base URL override (for proxies or local models)"
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Generation temperature (lower = more deterministic)"
    )
    llm_max_tokens: int = Field(
        default=4096,
        ge=100,
        le=32000,
        description="Maximum tokens in response"
    )
    
    # -------------------------------------------------------------------------
    # RAG Configuration
    # -------------------------------------------------------------------------
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model for embeddings"
    )
    vector_store_path: Path = Field(
        default=Path("./data/vector_store"),
        description="Path to ChromaDB persistent storage"
    )
    chunk_size: int = Field(
        default=512,
        ge=100,
        le=2000,
        description="Document chunk size for ingestion"
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        le=500,
        description="Overlap between chunks"
    )
    
    # -------------------------------------------------------------------------
    # Retrieval Confidence Thresholds
    # -------------------------------------------------------------------------
    global_min_confidence: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Global minimum retrieval confidence threshold"
    )
    food_properties_confidence: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for food properties retrieval"
    )
    pathogen_hazards_confidence: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for pathogen hazards retrieval"
    )
    
    # -------------------------------------------------------------------------
    # Clarification Loop
    # -------------------------------------------------------------------------
    max_clarification_turns: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum clarification requests before applying defaults"
    )
    
    # -------------------------------------------------------------------------
    # Conservative Defaults (Safety-Critical)
    # -------------------------------------------------------------------------
    default_temperature_abuse_c: float = Field(
        default=25.0,
        description="Conservative ambient temperature assumption (°C)"
    )
    default_ph_neutral: float = Field(
        default=7.0,
        ge=0.0,
        le=14.0,
        description="Default pH when unknown"
    )
    default_water_activity: float = Field(
        default=0.99,
        ge=0.0,
        le=1.0,
        description="Default water activity when unknown (conservative = high)"
    )
    
    # -------------------------------------------------------------------------
    # Engine Configuration (connection settings only, NOT constraints)
    # -------------------------------------------------------------------------
    combase_api_url: Optional[str] = Field(
        default=None,
        description="ComBase API endpoint URL"
    )
    combase_timeout_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout for ComBase API calls"
    )
    
    # -------------------------------------------------------------------------
    # Constraint Cache Settings
    # -------------------------------------------------------------------------
    constraint_cache_ttl_seconds: int = Field(
        default=86400,
        ge=0,
        description="Time-to-live for cached engine constraints (0 = no expiry)"
    )
    constraint_cache_path: Optional[Path] = Field(
        default=Path("./data/cache/constraints"),
        description="Path for persistent constraint cache (None = memory only)"
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