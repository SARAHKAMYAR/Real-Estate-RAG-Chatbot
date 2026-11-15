"""HTTP API and the chat page.

uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.agent import Agent
from app.config import get_settings
from app.db import close_pool, connection
from app.embeddings import get_embedder
from app.guards import DemoGuards
from app.llm import LLMError, LLMNotConfigured, get_llm, is_configured, selected_provider
from app.web import get_web_search

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    allow_web: bool = True


class SourceOut(BaseModel):
    ref: int
    kind: Literal["document", "listing", "web"]
    key: str
    title: str
    locator: str
    snippet: str
    url: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    used_web: bool
    latency_ms: int


@lru_cache
def get_agent() -> Agent:
    settings = get_settings()
    try:
        llm = get_llm(settings)
    except LLMNotConfigured as exc:
        raise HTTPException(503, f"The assistant is not configured. {exc}") from exc
    return Agent(llm, get_embedder(), get_web_search(), settings)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    yield
    close_pool()


app = FastAPI(title="Real Estate RAG Chatbot", version="1.1.0", lifespan=lifespan)
app.add_middleware(DemoGuards)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().allowed_hosts)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    try:
        with connection() as conn:
            counts = conn.execute(
                "SELECT (SELECT count(*) FROM documents) AS documents, "
                "(SELECT count(*) FROM chunks) AS chunks, "
                "(SELECT count(*) FROM listings) AS listings"
            ).fetchone()
    except Exception as exc:
        log.exception("health check failed")
        raise HTTPException(503, "Database unavailable.") from exc
    return {
        "status": "ok",
        **counts,
        "llm_provider": selected_provider(settings),
        "llm_configured": is_configured(settings),
        "web_search_configured": bool(settings.tavily_api_key),
    }


# A plain `def` endpoint: FastAPI runs it in a worker thread, so the blocking model and
# database calls do not stall other requests.
@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, agent: Agent = Depends(get_agent)) -> ChatResponse:  # noqa: B008
    try:
        result = agent.answer(
            request.message,
            history=[turn.model_dump() for turn in request.history],
            allow_web=request.allow_web,
        )
    except LLMError as exc:
        log.error("model call failed: %s", exc)
        detail = str(exc) if exc.status != 502 else "The assistant could not answer right now."
        raise HTTPException(exc.status, detail) from exc

    return ChatResponse(
        answer=result.answer,
        sources=[SourceOut(**source.to_dict()) for source in result.sources],
        used_web=result.used_web,
        latency_ms=result.latency_ms,
    )
