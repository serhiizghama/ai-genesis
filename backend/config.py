"""Configuration settings for AI-Genesis — loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with env-driven overrides.

    All values can be overridden via environment variables prefixed with GENESIS_.
    Example: GENESIS_TICK_RATE_MS=32 overrides tick_rate_ms.
    """

    # Core simulation parameters
    tick_rate_ms: int = 16
    max_entities: int = 500
    min_population: int = 20
    world_width: int = 2000
    world_height: int = 2000

    # Redis connection
    redis_url: str = "redis://redis:6379/0"

    # PostgreSQL connection (used in later phases)
    postgres_dsn: str = "postgresql+asyncpg://genesis:genesis@postgres:5432/genesis"

    # Ollama LLM service
    ollama_url: str = "http://ollama:11434"
    ollama_model: str = "llama3:8b"
    llm_timeout_sec: int = 120

    # Sandbox safety limits
    mutations_dir: str = "./mutations"
    trait_timeout_sec: float = 0.005  # 5ms hard limit per trait
    tick_time_budget_sec: float = 0.014  # 14ms budget for entire tick
    max_active_traits: int = 30
    max_trait_versions_kept: int = 3  # Keep only last 3 versions for GC
    allowed_imports: str = "math,random,dataclasses,typing,enum,collections,functools,itertools"

    # Process management
    soft_restart_interval_hours: int = 24  # Auto-restart for memory cleanup
    soft_restart_mutation_threshold: int = 1000  # Or when N mutations reached

    # Watcher agent
    snapshot_interval_ticks: int = 300
    watcher_history_depth: int = 5
    anomaly_death_threshold: float = 0.30
    anomaly_overpop_threshold: float = 2.0

    # Evolution cycle
    evolution_cooldown_sec: int = 60

    model_config = SettingsConfigDict(
        env_prefix="GENESIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
