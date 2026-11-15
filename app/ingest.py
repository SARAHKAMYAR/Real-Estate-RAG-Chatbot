"""Load company documents and listings into Postgres.

    python -m app.ingest

Ingestion is incremental: a document or listing is re-embedded only when its content (or the
embedding model) has changed, and rows whose source has been removed from disk are deleted.
"""

import argparse
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import BaseModel, ConfigDict, Field

from app.chunking import parse_markdown
from app.config import get_settings
from app.db import close_pool, connection
from app.embeddings import Embedder, get_embedder

log = logging.getLogger(__name__)

LISTING_COLUMNS = [
    "id", "title", "address", "city", "neighbourhood", "listing_type", "status", "price_eur",
    "property_type", "bedrooms", "bathrooms", "area_m2", "year_built", "energy_label",
    "features", "pets_allowed", "service_costs_eur_month", "available_from", "description",
]  # fmt: skip


class ListingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^NL-\d{4}$")
    title: str = Field(min_length=1)
    address: str = Field(min_length=1)
    city: str = Field(min_length=1)
    neighbourhood: str = Field(min_length=1)
    listing_type: Literal["sale", "rent"]
    status: Literal["available", "under_offer"]
    price_eur: int = Field(ge=0)
    property_type: str = Field(min_length=1)
    bedrooms: int = Field(ge=0)
    bathrooms: int = Field(ge=0)
    area_m2: int = Field(gt=0)
    year_built: int = Field(ge=0)
    energy_label: str = Field(min_length=1)
    features: list[str]
    pets_allowed: bool | None
    service_costs_eur_month: int | None = Field(ge=0)
    available_from: date | None
    description: str = Field(min_length=1)


def document_paths(directory: Path, *, allow_empty: bool = False) -> list[Path]:
    if not directory.is_dir():
        raise ValueError(f"Documents directory does not exist: {directory}")
    paths = sorted(directory.glob("*.md"))
    if not paths and not allow_empty:
        raise ValueError(
            "No Markdown documents found; refusing to erase the index. "
            "Use --allow-empty deliberately."
        )
    for path in paths:
        parsed = parse_markdown(path.read_text(encoding="utf-8"), fallback_title=path.stem)
        if not parsed.chunks:
            raise ValueError(f"Document contains no indexable text: {path.name}")
    return paths


def load_listings(file: Path, *, allow_empty: bool = False) -> list[dict]:
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or (not raw and not allow_empty):
        raise ValueError(
            "Listings must be a nonempty JSON array; use --allow-empty for deliberate removal."
        )
    listings = [ListingInput.model_validate(item).model_dump(mode="json") for item in raw]
    if len({item["id"] for item in listings}) != len(listings):
        raise ValueError("Listing IDs must be unique.")
    return listings


@dataclass
class IngestReport:
    documents_indexed: int = 0
    documents_unchanged: int = 0
    documents_removed: int = 0
    chunks_written: int = 0
    listings_indexed: int = 0
    listings_unchanged: int = 0
    listings_removed: int = 0


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def listing_text(listing: dict) -> str:
    """The text that represents a listing for semantic search."""
    kind = "for rent" if listing["listing_type"] == "rent" else "for sale"
    bedrooms = "studio" if listing["bedrooms"] == 0 else f"{listing['bedrooms']} bedrooms"
    return (
        f"{listing['title']}. {listing['property_type']} {kind} in "
        f"{listing['neighbourhood']}, {listing['city']}. {bedrooms}, {listing['area_m2']} m2, "
        f"built {listing['year_built']}, energy label {listing['energy_label']}. "
        f"Features: {', '.join(listing['features'])}. {listing['description']}"
    )


def ingest_documents(
    conn: psycopg.Connection,
    embedder: Embedder,
    directory: Path,
    model: str,
    report: IngestReport,
    *,
    allow_empty: bool = False,
) -> None:
    paths = document_paths(directory, allow_empty=allow_empty)
    existing = {
        row["source_path"]: row["content_hash"]
        for row in conn.execute("SELECT source_path, content_hash FROM documents")
    }

    for path in paths:
        text = path.read_text(encoding="utf-8")
        content_hash = _hash(model, text)
        if existing.get(path.name) == content_hash:
            report.documents_unchanged += 1
            continue

        parsed = parse_markdown(text, fallback_title=path.stem.replace("-", " ").title())
        vectors = embedder.embed_passages(
            [f"{parsed.title} - {c.heading}\n{c.content}" for c in parsed.chunks]
        )
        with conn.transaction():
            conn.execute("DELETE FROM documents WHERE source_path = %s", (path.name,))
            document_id = conn.execute(
                "INSERT INTO documents (source_path, title, content_hash) VALUES (%s, %s, %s) "
                "RETURNING id",
                (path.name, parsed.title, content_hash),
            ).fetchone()["id"]
            for ordinal, (chunk, vector) in enumerate(zip(parsed.chunks, vectors, strict=True)):
                conn.execute(
                    "INSERT INTO chunks (document_id, ordinal, heading, content, embedding) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (document_id, ordinal, chunk.heading, chunk.content, vector),
                )
        report.documents_indexed += 1
        report.chunks_written += len(parsed.chunks)
        log.info("indexed %s (%d chunks)", path.name, len(parsed.chunks))

    removed = set(existing) - {p.name for p in paths}
    if removed:
        conn.execute("DELETE FROM documents WHERE source_path = ANY(%s)", (list(removed),))
        report.documents_removed = len(removed)


def ingest_listings(
    conn: psycopg.Connection,
    embedder: Embedder,
    file: Path,
    model: str,
    report: IngestReport,
    *,
    allow_empty: bool = False,
) -> None:
    listings = load_listings(file, allow_empty=allow_empty)
    existing = {
        row["id"]: row["content_hash"]
        for row in conn.execute("SELECT id, content_hash FROM listings")
    }

    changed = []
    for listing in listings:
        content_hash = _hash(model, json.dumps(listing, sort_keys=True))
        if existing.get(listing["id"]) == content_hash:
            report.listings_unchanged += 1
        else:
            changed.append((listing, content_hash))

    if changed:
        vectors = embedder.embed_passages([listing_text(listing) for listing, _ in changed])
        columns = [*LISTING_COLUMNS, "content_hash", "embedding"]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "id")
        sql = (
            f"INSERT INTO listings ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}"
        )
        with conn.transaction():
            for (listing, content_hash), vector in zip(changed, vectors, strict=True):
                conn.execute(sql, [*(listing[c] for c in LISTING_COLUMNS), content_hash, vector])
        report.listings_indexed = len(changed)

    removed = set(existing) - {listing["id"] for listing in listings}
    if removed:
        conn.execute("DELETE FROM listings WHERE id = ANY(%s)", (list(removed),))
        report.listings_removed = len(removed)


def run_ingest(*, allow_empty: bool = False) -> IngestReport:
    settings = get_settings()
    document_paths(settings.documents_dir, allow_empty=allow_empty)
    load_listings(settings.listings_file, allow_empty=allow_empty)
    embedder = get_embedder()
    report = IngestReport()
    with connection() as conn:
        ingest_documents(
            conn,
            embedder,
            settings.documents_dir,
            settings.embedding_model,
            report,
            allow_empty=allow_empty,
        )
        ingest_listings(
            conn,
            embedder,
            settings.listings_file,
            settings.embedding_model,
            report,
            allow_empty=allow_empty,
        )
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="allow deliberate removal of all indexed documents or listings",
    )
    args = parser.parse_args()
    try:
        print(run_ingest(allow_empty=args.allow_empty))
    finally:
        close_pool()
