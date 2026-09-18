"""Assistant settings. Commands are run from the assistant directory."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ASSISTANT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", env_ignore_empty=True, extra="ignore"
    )

    ollama_url: str = "http://localhost:11434"
    assistant_model: str = "qwen3.5:0.8b"
    llm_timeout_seconds: float = 120.0
    llm_temperature: float = 0.3
    llm_num_ctx: int = 8192
    llm_max_tokens: int = 400
    # Ollama in Docker Desktop on Apple Silicon also schedules on efficiency cores and
    # generates ~3x slower; set this to the number of performance cores there.
    llm_num_thread: int | None = None
    knowledge_dir: Path = ASSISTANT_ROOT / "knowledge"
    retrieval_top_k: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
