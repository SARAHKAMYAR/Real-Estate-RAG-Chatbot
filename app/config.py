from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DATA_ROOT = Path(__file__).resolve().parent / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/realestate"

    # "groq" (default, free tier) or "anthropic". Claude is only used when chosen explicitly.
    llm_provider: str = "groq"

    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    llm_effort: str = "medium"
    llm_max_tokens: int = Field(4096, ge=256, le=16000)
    provider_timeout_seconds: float = Field(30.0, ge=1, le=120)
    # On a safety-classifier decline, let the API retry on a fallback model in the same call.
    llm_refusal_fallback: bool = True

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # Groq counts this reservation against the per-minute token limit, so keep it modest.
    groq_max_tokens: int = 2048
    # For Groq reasoning models: low | medium | high. Empty leaves the provider default.
    groq_reasoning_effort: str = "medium"
    # Interactive requests fail promptly on rate limits; batch jobs may opt into one wait.
    groq_rate_limit_waits: int = Field(0, ge=0, le=1)

    # Upper bound on model <-> tool round trips for one question.
    agent_max_steps: int = Field(6, ge=1, le=8)
    agent_max_tool_calls: int = Field(12, ge=1, le=24)
    agent_timeout_seconds: float = Field(90.0, ge=1, le=300)

    # Local-demo safeguards; limits are per process, not distributed account quotas.
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "[::1]", "testserver"]
    chat_requests_per_minute: int = Field(30, ge=1, le=1000)
    chat_max_concurrent: int = Field(2, ge=1, le=16)
    chat_max_body_bytes: int = Field(131072, ge=4096, le=1048576)

    tavily_api_key: str = ""
    web_max_results: int = Field(4, ge=1, le=8)
    # Public authorities only by default. Set a JSON list to deliberately broaden sources.
    web_allowed_domains: list[str] = ["rijksoverheid.nl", "government.nl", "belastingdienst.nl"]

    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = Field(384, ge=1, le=2000)

    retrieval_top_k: int = Field(5, ge=1, le=20)
    # Candidates taken from each of the vector and keyword rankings before fusion.
    retrieval_candidates: int = Field(20, ge=20, le=200)

    documents_dir: Path = DATA_ROOT / "documents"
    listings_file: Path = DATA_ROOT / "listings.json"

    company_name: str = "Noorderlicht Makelaars"


@lru_cache
def get_settings() -> Settings:
    return Settings()
