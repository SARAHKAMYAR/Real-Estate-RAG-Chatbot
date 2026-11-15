"""The agent loop and the HTTP API, with the model and the database replaced by fakes."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.tools as tools
from app.agent import Agent, AgentResult
from app.config import Settings
from app.llm import AnthropicLLM, GroqLLM
from app.main import app, get_agent
from app.retrieval import DocumentHit
from app.sources import Source


def _response(stop_reason, *blocks):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use(name, arguments, id_="tu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=id_)


class FakeClient:
    """Replays scripted model responses and records every request."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return self._responses.pop(0)


@pytest.fixture
def fake_search(monkeypatch):
    @contextmanager
    def no_connection():
        yield None

    hit = DocumentHit(1, "rental-policy.md", "Rental Policy", "Deposit", "Two months' rent.", 0.03)
    monkeypatch.setattr(tools, "connection", no_connection)
    monkeypatch.setattr(tools, "search_documents", lambda conn, embedder, query: [hit])


def _agent(client, web_search=None, **overrides):
    settings = Settings(_env_file=None, anthropic_api_key="test", **overrides)
    llm = AnthropicLLM(client, settings)
    return Agent(llm, embedder=None, web_search=web_search, settings=settings)


def test_agent_searches_then_answers_with_only_cited_sources(fake_search):
    client = FakeClient(
        _response("tool_use", _tool_use("search_documents", {"query": "deposit"})),
        _response("end_turn", _text("The deposit is two months' rent [1]. See also [4].")),
    )
    result = _agent(client).answer(
        "How big is the deposit?",
        history=[
            {"role": "assistant", "content": "Hello [2]"},
            {"role": "user", "content": "Hi"},
        ],
    )

    assert result.answer == "The deposit is two months' rent [1]. See also."
    assert [(s.kind, s.key, s.locator) for s in result.sources] == [
        ("document", "rental-policy.md", "Deposit")
    ]
    assert result.tool_calls == [
        {"name": "search_documents", "input": {"query": "deposit"}, "error": False}
    ]
    assert (result.input_tokens, result.output_tokens) == (20, 10)

    first, second = client.requests
    # the leading assistant turn is dropped; earlier answers are replayed without citations
    assert [m["content"] for m in first["messages"]] == ["Hi", "How big is the deposit?"]
    assert "web_search" not in {t["name"] for t in first["tools"]}
    tool_result = second["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu_1"
    assert '"ref": 1' in tool_result["content"]


def test_web_tool_is_offered_only_when_configured_and_allowed(fake_search):
    def web(query):
        return [{"title": "Gov", "url": "https://example.org/tax", "content": "2%"}]

    client = FakeClient(
        _response("tool_use", _tool_use("web_search", {"query": "transfer tax"})),
        _response("end_turn", _text("According to example.org it is 2% [1].")),
        _response("end_turn", _text("I couldn't find that.")),
    )
    agent = _agent(client, web_search=web)

    result = agent.answer("What is the transfer tax?")
    assert result.used_web and result.sources[0].url == "https://example.org/tax"
    assert "web_search" in {t["name"] for t in client.requests[0]["tools"]}

    agent.answer("Again?", allow_web=False)
    assert "web_search" not in {t["name"] for t in client.requests[-1]["tools"]}


def test_tool_failures_are_reported_to_the_model_not_raised(fake_search):
    client = FakeClient(
        _response("tool_use", _tool_use("search_listings", {"max_price_eur": -5})),
        _response("end_turn", _text("I couldn't find that.")),
    )
    result = _agent(client).answer("?")
    assert result.tool_calls[0]["error"] is True
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True


def test_agent_stops_after_the_step_limit(fake_search):
    looping = [
        _response("tool_use", _tool_use("search_documents", {"query": "x"}, f"tu_{i}"))
        for i in range(3)
    ]
    client = FakeClient(*looping)
    result = _agent(client, agent_max_steps=3).answer("?")
    assert len(client.requests) == 3
    assert "couldn't put together" in result.answer and result.sources == []


def test_refusal_is_turned_into_a_plain_message(fake_search):
    client = FakeClient(_response("refusal"))
    assert _agent(client).answer("?").answer == "I'm not able to help with that request."


class FakeGroqClient:
    """Replays scripted chat-completion responses in the OpenAI wire shape."""

    def __init__(self, *messages):
        self._messages = list(messages)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        message = self._messages.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        )


def test_groq_provider_runs_the_same_loop(fake_search):
    call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(name="search_documents", arguments='{"query": "deposit"}'),
    )
    client = FakeGroqClient(
        SimpleNamespace(content=None, tool_calls=[call]),
        SimpleNamespace(content="Two months' rent [1].", tool_calls=None),
    )
    settings = Settings(_env_file=None, groq_api_key="test")
    agent = Agent(GroqLLM(client, settings), embedder=None, settings=settings)

    result = agent.answer("How big is the deposit?")

    assert result.answer == "Two months' rent [1]."
    assert [s.key for s in result.sources] == ["rental-policy.md"]
    assert (result.input_tokens, result.output_tokens) == (14, 6)
    first, second = client.requests
    assert first["messages"][0]["role"] == "system"
    assert first["tools"][0]["function"]["name"] == "search_documents"
    listing_params = first["tools"][1]["function"]["parameters"]["properties"]
    assert listing_params["city"]["type"] == ["string", "null"]  # optional filters accept null
    assert listing_params["listing_type"]["enum"] == ["sale", "rent", None]
    assert [m["role"] for m in second["messages"]] == ["system", "user", "assistant", "tool"]
    assert second["messages"][-1]["tool_call_id"] == "call_1"


def test_groq_is_the_default_and_claude_needs_an_explicit_choice():
    from app.llm import LLMNotConfigured, get_llm, is_configured

    both_keys = Settings(_env_file=None, groq_api_key="g", anthropic_api_key="a")
    assert isinstance(get_llm(both_keys), GroqLLM)

    claude_key_only = Settings(_env_file=None, anthropic_api_key="a")
    assert not is_configured(claude_key_only)
    with pytest.raises(LLMNotConfigured):
        get_llm(claude_key_only)

    explicit = Settings(_env_file=None, llm_provider="anthropic", anthropic_api_key="a")
    assert isinstance(get_llm(explicit), AnthropicLLM)

    with pytest.raises(LLMNotConfigured):
        get_llm(Settings(_env_file=None, llm_provider="other", groq_api_key="g"))


def test_chat_endpoint_returns_answer_and_sources():
    source = Source(1, "listing", "NL-1005", "NL-1005 - Jordaan", "Bloemgracht 77", "desc")

    class StubAgent:
        def answer(self, question, history, allow_web):
            assert question == "Price of NL-1005?" and history == [] and allow_web is True
            return AgentResult(
                answer="€795,000 [1].", sources=[source], retrieved=[source], latency_ms=12
            )

    app.dependency_overrides[get_agent] = lambda: StubAgent()
    try:
        client = TestClient(app)
        response = client.post("/api/chat", json={"message": "Price of NL-1005?"})
        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "€795,000 [1]."
        assert body["sources"][0]["key"] == "NL-1005" and body["used_web"] is False
        assert client.post("/api/chat", json={"message": ""}).status_code == 422
        assert client.get("/").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_agent_enforces_total_tool_call_budget(fake_search):
    from app.llm import LLMError

    client = FakeClient(
        _response(
            "tool_use",
            *[_tool_use("search_documents", {"query": "deposit"}, f"t{i}") for i in range(3)],
        )
    )
    with pytest.raises(LLMError, match="too many searches") as error:
        _agent(client, agent_max_tool_calls=1).answer("deposit?")
    assert error.value.status == 422


def test_agent_enforces_elapsed_budget_before_next_provider_call(fake_search, monkeypatch):
    from app.llm import LLMError

    ticks = [0.0, 100.0]
    monkeypatch.setattr(
        "app.agent.time.perf_counter", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0]
    )
    client = FakeClient()
    with pytest.raises(LLMError, match="too long"):
        _agent(client, agent_timeout_seconds=1).answer("deposit?")
    assert client.requests == []
