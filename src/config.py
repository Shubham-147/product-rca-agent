"""Environment and application settings loader."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    openai_api_key: str = Field(...)
    openai_model: str = "gpt-4o-mini"

    @field_validator("openai_api_key")
    @classmethod
    def _key_must_be_present(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError(
                "OPENAI_API_KEY is missing or empty. "
                "Copy .env.example to .env and set your API key."
            )
        return value.strip()


@lru_cache
def get_settings() -> Settings:
    """Load and validate settings from .env (cached after first call)."""
    load_dotenv(_ENV_PATH)
    import os

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        raise RuntimeError(
            "OPENAI_API_KEY is not set. "
            "Create a .env file at the project root (see .env.example) "
            "and add your OpenAI API key."
        )

    return Settings(
        openai_api_key=api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )
