"""Runtime configuration — models, budgets, telemetry (design tenets #3, #6).

Everything that varies between "scaffold on a stub model" and "real runs against the
LiteLLM proxy" lives here, driven by env vars (prefix `RCA_`) or a `.env` file. With no
`RCA_LLM_BASE_URL` set, `build_model()` returns None and the system falls back to a
deterministic stub model — so the whole agent runs, tools fire, output validates, and
budgets enforce, all with no API key. Point it at the proxy by setting three env vars.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RCA_", env_file=".env", extra="ignore")

    # --- LLM (via self-hosted LiteLLM proxy; OpenAI-compatible) ---
    llm_base_url: str | None = None          # e.g. http://localhost:4000
    llm_api_key: str | None = None           # LiteLLM key (proxy governs the real ones)
    model_name: str = "gpt-4o"               # strong model for System B
    model_name_cheap: str = "gpt-4o-mini"    # tiered/cheap tasks
    temperature: float = 0.0                 # determinism (tenet #3)

    # --- budget / bounds (tenet #6) ---
    request_limit: int = 25                  # max model requests per run
    tool_calls_limit: int = 40               # max tool calls per run
    total_tokens_limit: int | None = 200_000 # hard token ceiling per run
    request_timeout_s: float = 90.0          # per-request network timeout (no infinite hang)
    max_output_tokens: int = 4096            # cap per response (16k default is wasteful here)
    usd_per_run_cap: float = 0.15            # reported + enforced (see llm cost table)

    # --- telemetry (Langfuse via OpenTelemetry; activates when keys are set) ---
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_base_url)

    @property
    def has_langfuse(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def build_model(settings: Settings | None = None):
    """Return a configured pydantic-ai model, or None to signal 'use the stub'."""
    settings = settings or get_settings()
    if not settings.has_llm:
        return None
    import httpx
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    # Hard network timeout at the client level (model_settings 'timeout' isn't always
    # honored) so a stalled connection can never hang a run indefinitely.
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout_s, connect=10.0)
    )
    provider = OpenAIProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "sk-noop",
        http_client=http_client,
    )
    return OpenAIChatModel(settings.model_name, provider=provider)
