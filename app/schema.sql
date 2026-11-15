CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id            BIGSERIAL PRIMARY KEY,
    source_path   TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id           BIGSERIAL PRIMARY KEY,
    document_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      INT NOT NULL,
    heading      TEXT NOT NULL,
    content      TEXT NOT NULL,
    embedding    vector({dim}) NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (
                     setweight(to_tsvector('english', heading), 'A') ||
                     setweight(to_tsvector('english', content), 'B')
                 ) STORED,
    UNIQUE (document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS listings (
    id                       TEXT PRIMARY KEY,
    title                    TEXT NOT NULL,
    address                  TEXT NOT NULL,
    city                     TEXT NOT NULL,
    neighbourhood            TEXT NOT NULL,
    listing_type             TEXT NOT NULL CHECK (listing_type IN ('sale', 'rent')),
    status                   TEXT NOT NULL CHECK (status IN ('available', 'under_offer')),
    price_eur                INT NOT NULL,
    property_type            TEXT NOT NULL,
    bedrooms                 INT NOT NULL,
    bathrooms                INT NOT NULL,
    area_m2                  INT NOT NULL,
    year_built               INT NOT NULL,
    energy_label             TEXT NOT NULL,
    features                 TEXT[] NOT NULL DEFAULT '{}',
    pets_allowed             BOOLEAN,
    service_costs_eur_month  INT,
    available_from           DATE,
    description              TEXT NOT NULL,
    content_hash             TEXT NOT NULL,
    embedding                vector({dim}) NOT NULL,
    tsv                      tsvector GENERATED ALWAYS AS (
                                 setweight(to_tsvector('english', title || ' ' || city || ' ' || neighbourhood), 'A') ||
                                 setweight(to_tsvector('english', description), 'B')
                             ) STORED
);

CREATE INDEX IF NOT EXISTS listings_embedding_idx ON listings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS listings_tsv_idx ON listings USING gin (tsv);
CREATE INDEX IF NOT EXISTS listings_filter_idx ON listings (listing_type, city, price_eur);
