"""Search against the real database. Skipped when Postgres is not reachable."""

import os

import psycopg
import pytest

from app.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def search():
    try:
        psycopg.connect(get_settings().database_url, connect_timeout=2).close()
    except psycopg.OperationalError:
        if os.getenv("REQUIRE_INTEGRATION") == "1":
            pytest.fail("Postgres is required for this test run but is unavailable")
        pytest.skip("Postgres is not running")

    from app.db import close_pool, connection
    from app.embeddings import get_embedder
    from app.ingest import run_ingest

    run_ingest()
    with connection() as conn:
        yield conn, get_embedder()
    close_pool()


@pytest.mark.parametrize(
    ("question", "document"),
    [
        ("What commission do you charge for selling a home?", "fees-and-commission.md"),
        ("Can I keep a dog in a rental apartment?", "rental-policy.md"),
        ("How long is the cooling-off period?", "buying-guide.md"),
        ("Who do I call when a pipe bursts at night?", "offices-and-contact.md"),
    ],
)
def test_document_search_finds_the_right_document(search, question, document):
    from app.retrieval import search_documents

    conn, embedder = search
    assert document in [hit.source_path for hit in search_documents(conn, embedder, question)]


def test_listing_filters_are_exact(search):
    from app.retrieval import ListingFilters, get_listing, search_listings

    conn, embedder = search

    def ids(**filters):
        return [item.id for item in search_listings(conn, embedder, ListingFilters(**filters))]

    assert ids(city="utrecht", listing_type="sale", max_price_eur=500000) == ["NL-1003", "NL-1001"]
    assert set(ids(listing_type="rent", pets_allowed=True)) == {"NL-2002", "NL-2003", "NL-2006"}
    assert ids(city="Rotterdam", listing_type="sale", features=["private parking"]) == ["NL-1012"]
    assert set(ids(listing_type="sale", min_bedrooms=4, features=["solar"])) == {
        "NL-1002",
        "NL-1010",
    }
    assert ids(query="houseboat on the river", limit=1) == ["NL-1007"]
    assert ids(city="Groningen") == []
    assert get_listing(conn, "nl-1005").price_eur == 795000


def test_ingest_is_incremental(search):
    from app.ingest import run_ingest

    report = run_ingest()
    assert report.documents_indexed == 0 and report.listings_indexed == 0
    assert report.documents_unchanged == 10 and report.listings_unchanged == 19
