"""Search over company documents and listings.

Document search is hybrid: a vector ranking (meaning) and a full-text ranking (exact words such
as "NWWI" or "Open Bod") are combined with reciprocal rank fusion. Listing search applies hard
filters in SQL first - a price ceiling must never be a matter of similarity - and only then
ranks what is left.
"""

from dataclasses import asdict, dataclass
from typing import Literal

import psycopg
from pydantic import BaseModel, Field

from app.config import get_settings
from app.embeddings import Embedder

RRF_K = 60

# Turns free text into an OR query: any shared term makes a chunk a keyword candidate, and
# ts_rank_cd then orders candidates by how many terms match and how close together they are.
_OR_TSQUERY = (
    "(SELECT NULLIF(replace(plainto_tsquery('english', %(text)s)::text, '&', '|'), '')"
    "::tsquery AS q)"
)


def reciprocal_rank_fusion(rankings: list[list], k: int = RRF_K) -> list[tuple[object, float]]:
    """Fuse ranked id lists; an id scores sum(1 / (k + rank)) over the lists it appears in."""
    scores: dict[object, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


@dataclass(frozen=True)
class DocumentHit:
    chunk_id: int
    source_path: str
    title: str
    heading: str
    content: str
    score: float


def search_documents(
    conn: psycopg.Connection, embedder: Embedder, query: str, top_k: int | None = None
) -> list[DocumentHit]:
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    params = {
        "embedding": embedder.embed_query(query),
        "text": query,
        "n": settings.retrieval_candidates,
    }

    by_vector = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM chunks ORDER BY embedding <=> %(embedding)s LIMIT %(n)s", params
        )
    ]
    by_keyword = [
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM chunks, {_OR_TSQUERY} AS kw WHERE tsv @@ kw.q "
            "ORDER BY ts_rank_cd(tsv, kw.q) DESC LIMIT %(n)s",
            params,
        )
    ]

    fused = reciprocal_rank_fusion([by_vector, by_keyword])[:top_k]
    if not fused:
        return []
    scores = dict(fused)
    rows = conn.execute(
        "SELECT c.id, d.source_path, d.title, c.heading, c.content "
        "FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(%s)",
        (list(scores),),
    ).fetchall()
    hits = [
        DocumentHit(
            r["id"], r["source_path"], r["title"], r["heading"], r["content"], scores[r["id"]]
        )
        for r in rows
    ]
    return sorted(hits, key=lambda hit: hit.score, reverse=True)


class ListingFilters(BaseModel):
    """Structured filters for listing search. Every field is optional."""

    query: str | None = Field(None, description="Free-text description of what the person wants.")
    listing_type: Literal["sale", "rent"] | None = None
    city: str | None = None
    property_type: str | None = None
    min_price_eur: int | None = Field(None, ge=0)
    max_price_eur: int | None = Field(None, ge=0)
    min_bedrooms: int | None = Field(None, ge=0)
    min_area_m2: int | None = Field(None, ge=0)
    features: list[str] = Field(default_factory=list)
    pets_allowed: bool | None = None
    include_under_offer: bool = True
    limit: int = Field(8, ge=1, le=20)


_LISTING_FIELDS = (
    "id, title, address, city, neighbourhood, listing_type, status, price_eur, property_type, "
    "bedrooms, bathrooms, area_m2, year_built, energy_label, features, pets_allowed, "
    "service_costs_eur_month, available_from, description"
)


@dataclass(frozen=True)
class Listing:
    id: str
    title: str
    address: str
    city: str
    neighbourhood: str
    listing_type: str
    status: str
    price_eur: int
    property_type: str
    bedrooms: int
    bathrooms: int
    area_m2: int
    year_built: int
    energy_label: str
    features: list[str]
    pets_allowed: bool | None
    service_costs_eur_month: int | None
    available_from: str | None
    description: str

    @classmethod
    def from_row(cls, row: dict) -> "Listing":
        available = row["available_from"]
        return cls(**{**row, "available_from": available.isoformat() if available else None})

    def to_dict(self) -> dict:
        return asdict(self)


def _listing_where(filters: ListingFilters) -> tuple[str, dict]:
    clauses: list[str] = []
    params: dict = {}

    def add(clause: str, **values) -> None:
        clauses.append(clause)
        params.update(values)

    if filters.listing_type:
        add("listing_type = %(listing_type)s", listing_type=filters.listing_type)
    if filters.city:
        add("lower(city) = lower(%(city)s)", city=filters.city.strip())
    if filters.property_type:
        add(
            "property_type ILIKE %(property_type)s",
            property_type=f"%{filters.property_type.strip()}%",
        )
    if filters.min_price_eur is not None:
        add("price_eur >= %(min_price)s", min_price=filters.min_price_eur)
    if filters.max_price_eur is not None:
        add("price_eur <= %(max_price)s", max_price=filters.max_price_eur)
    if filters.min_bedrooms is not None:
        add("bedrooms >= %(min_bedrooms)s", min_bedrooms=filters.min_bedrooms)
    if filters.min_area_m2 is not None:
        add("area_m2 >= %(min_area)s", min_area=filters.min_area_m2)
    if filters.pets_allowed is not None:
        add("pets_allowed = %(pets)s", pets=filters.pets_allowed)
    if not filters.include_under_offer:
        clauses.append("status = 'available'")
    for i, feature in enumerate(filters.features):
        add(
            f"EXISTS (SELECT 1 FROM unnest(features) AS f WHERE f ILIKE %(feature_{i})s)",
            **{f"feature_{i}": f"%{feature.strip()}%"},
        )
    return (" AND ".join(clauses) or "TRUE"), params


def search_listings(
    conn: psycopg.Connection, embedder: Embedder, filters: ListingFilters
) -> list[Listing]:
    where, params = _listing_where(filters)

    if not filters.query:
        rows = conn.execute(
            f"SELECT {_LISTING_FIELDS} FROM listings WHERE {where} "
            "ORDER BY price_eur LIMIT %(limit)s",
            {**params, "limit": filters.limit},
        ).fetchall()
        return [Listing.from_row(row) for row in rows]

    params = {
        **params,
        "embedding": embedder.embed_query(filters.query),
        "text": filters.query,
        "candidates": get_settings().retrieval_candidates,
    }
    by_vector = [
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM listings WHERE {where} ORDER BY embedding <=> %(embedding)s "
            "LIMIT %(candidates)s",
            params,
        )
    ]
    by_keyword = [
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM listings, {_OR_TSQUERY} AS kw WHERE {where} AND tsv @@ kw.q "
            "ORDER BY ts_rank_cd(tsv, kw.q) DESC LIMIT %(candidates)s",
            params,
        )
    ]
    ranked = [item for item, _ in reciprocal_rank_fusion([by_vector, by_keyword])][: filters.limit]
    if not ranked:
        return []
    rows = conn.execute(
        f"SELECT {_LISTING_FIELDS} FROM listings WHERE id = ANY(%s)", (ranked,)
    ).fetchall()
    by_id = {row["id"]: Listing.from_row(row) for row in rows}
    return [by_id[item] for item in ranked]


def get_listing(conn: psycopg.Connection, listing_id: str) -> Listing | None:
    row = conn.execute(
        f"SELECT {_LISTING_FIELDS} FROM listings WHERE upper(id) = upper(%s)", (listing_id.strip(),)
    ).fetchone()
    return Listing.from_row(row) if row else None
