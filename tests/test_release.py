"""Regression checks for release safety, using no real API keys or database."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db
from app.config import Settings
from app.guards import DemoGuards
from app.ingest import IngestReport, document_paths, ingest_documents, load_listings, run_ingest
from app.sources import SourceRegistry, is_safe_url
from app.web import TavilyWebSearch
from evals import run


def test_missing_and_empty_documents_never_issue_sql(tmp_path):
    class NoSQL:
        def execute(self, *args):
            pytest.fail("No SQL may run for invalid input")

    for directory in (tmp_path / "missing", tmp_path):
        with pytest.raises(ValueError):
            ingest_documents(NoSQL(), None, directory, "test", IngestReport())
    assert document_paths(tmp_path, allow_empty=True) == []
    with pytest.raises(ValueError):
        document_paths(tmp_path / "missing", allow_empty=True)


def test_preflight_rejects_invalid_listings_before_loading_model(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "policy.md").write_text("# Policy\n\nValid text.")
    listings = tmp_path / "listings.json"
    listings.write_text('[{"id": "missing-fields"}]')
    settings = Settings(_env_file=None, documents_dir=documents, listings_file=listings)
    monkeypatch.setattr("app.ingest.get_settings", lambda: settings)
    monkeypatch.setattr("app.ingest.get_embedder", lambda: pytest.fail("Model loaded too early"))
    with pytest.raises(ValueError):
        run_ingest()


def test_listings_validate_before_deletion(tmp_path):
    file = tmp_path / "listings.json"
    file.write_text("[]")
    with pytest.raises(ValueError):
        load_listings(file)
    assert load_listings(file, allow_empty=True) == []
    sample = load_listings(Settings(_env_file=None).listings_file)
    file.write_text(json.dumps([sample[0], sample[0]]))
    with pytest.raises(ValueError, match="unique"):
        load_listings(file)


def test_citation_snippets_remain_distinct_and_repeat_stably():
    registry = SourceRegistry()
    one = registry.add("document", "long.md", "Long", "Fees", "First passage")
    two = registry.add("document", "long.md", "Long", "Fees", "Second passage")
    assert one != two
    assert registry.add("document", "long.md", "Long", "Fees", "Second passage") == two
    assert registry.get(two).snippet == "Second passage"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,test",
        "//evil.test",
        "https://user:secret@example.org",
        "https://example.org/\nfoo",
    ],
)
def test_unsafe_source_urls_are_rejected(url):
    assert not is_safe_url(url)
    registry = SourceRegistry()
    ref = registry.add("web", url, "Title", "Host", "Text", url=url)
    assert registry.get(ref).url is None


def test_web_results_must_match_authority_domains():
    search = object.__new__(TavilyWebSearch)
    captured = {}

    def fake_search(**kwargs):
        captured.update(kwargs)
        return {
            "results": [
                {"url": "https://www.belastingdienst.nl/rule", "content": "Official"},
                {"url": "https://belastingdienst.nl.evil.test/fake", "content": "Fake"},
                {"url": "javascript:alert(1)", "content": "Unsafe"},
            ]
        }

    search._client = SimpleNamespace(search=fake_search)
    search._domains = ["belastingdienst.nl"]
    search._timeout = 10
    search._max_results = 4
    results = search("tax exemption 2026")
    assert [r["content"] for r in results] == ["Official"]
    assert captured["include_domains"] == ["belastingdienst.nl"]
    assert captured["timeout"] == 10


def test_concurrent_first_use_creates_only_one_pool(monkeypatch):
    start, entered, release = Barrier(3), Event(), Event()
    pools = []

    def init():
        entered.set()
        assert release.wait(3)

    def constructor(*args, **kwargs):
        pool = object()
        pools.append(pool)
        return pool

    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "init_schema", init)
    monkeypatch.setattr(db, "ConnectionPool", constructor)

    def worker():
        start.wait(timeout=3)
        return db.get_pool()

    with ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        start.wait(timeout=3)
        assert entered.wait(3)
        release.set()
        results = [future.result(timeout=3) for future in futures]
    assert len(pools) == 1
    assert results[0] is results[1]


@pytest.mark.parametrize(("hits", "expected"), [(0, 1), (17, 0)])
def test_retrieval_threshold_controls_exit_status(tmp_path, monkeypatch, hits, expected):
    monkeypatch.setattr(
        run,
        "run_retrieval",
        lambda *args: {
            "top_k": 5,
            "hits": hits,
            "total": 17,
            "top1": hits,
            "mrr": hits / 17,
            "rows": [],
        },
    )
    monkeypatch.setattr(run, "close_pool", lambda: None)
    monkeypatch.setattr(run, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["eval", "--retrieval-only", "--min-retrieval-hits", "17"])
    assert run.main() == expected
    assert (tmp_path / "latest.json").is_file()


def test_retrieval_only_rejects_wrong_threshold_flag(monkeypatch):
    monkeypatch.setattr("sys.argv", ["eval", "--retrieval-only", "--min-score", "17"])
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 2


def guarded_app(monkeypatch, **overrides):
    settings = Settings(_env_file=None, **overrides)
    monkeypatch.setattr("app.guards.get_settings", lambda: settings)
    app = FastAPI()
    app.add_middleware(DemoGuards)

    @app.post("/api/chat")
    def chat():
        return {"answer": "Test"}

    return app


def test_rate_limit_rejects_without_calling_provider(monkeypatch):
    client = TestClient(guarded_app(monkeypatch, chat_requests_per_minute=2))
    assert client.post("/api/chat", json={}).status_code == 200
    assert client.post("/api/chat", json={}).status_code == 200
    response = client.post("/api/chat", json={})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


def test_streamed_body_limit_and_cross_origin_requests(monkeypatch):
    client = TestClient(guarded_app(monkeypatch, chat_max_body_bytes=4096))
    assert client.post("/api/chat", content=iter([b"x" * 3000, b"x" * 3000])).status_code == 413
    assert (
        client.post("/api/chat", json={}, headers={"Origin": "https://untrusted.test"}).status_code
        == 403
    )
    assert (
        client.post("/api/chat", json={}, headers={"Origin": "http://testserver"}).status_code
        == 200
    )


def test_concurrency_limit_does_not_queue_unlimited_model_calls(monkeypatch):
    app = guarded_app(monkeypatch, chat_max_concurrent=1)
    entered, release = Event(), Event()

    # Replace the endpoint so one real worker remains busy during the second request.
    @app.post("/api/unused")
    def unused():
        return {}

    route = next(route for route in app.routes if getattr(route, "path", "") == "/api/chat")

    def blocked():
        entered.set()
        assert release.wait(3)
        return {"answer": "done"}

    route.dependant.call = blocked
    client = TestClient(app)
    with ThreadPoolExecutor(1) as executor:
        first = executor.submit(client.post, "/api/chat", json={})
        assert entered.wait(3)
        try:
            assert client.post("/api/chat", json={}).status_code == 429
        finally:
            release.set()
        assert first.result(timeout=3).status_code == 200
    assert client.post("/api/chat", json={}).status_code == 200


def test_listing_source_exposes_the_price_used_in_calculations():
    from app.retrieval import Listing
    from app.tools import Toolbox

    record = load_listings(Settings(_env_file=None).listings_file)[0]
    listing = Listing(**record)
    registry = SourceRegistry()
    result = Toolbox(None, registry)._listing_result(listing)
    source = registry.get(result["ref"])
    assert f"EUR {listing.price_eur:,}" in source.snippet
    assert listing.status in source.snippet
