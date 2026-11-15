"""Postgres access: schema creation and a small connection pool with pgvector types registered."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_SCHEMA = Path(__file__).with_name("schema.sql")
_pool: ConnectionPool | None = None
_pool_lock = RLock()


def init_schema() -> None:
    """Create the extension, tables and indexes. Safe to run repeatedly."""
    settings = get_settings()
    sql = _SCHEMA.read_text().replace("{dim}", str(settings.embedding_dim))
    with psycopg.connect(settings.database_url, autocommit=True, connect_timeout=5) as conn:
        conn.execute(sql)


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)
    conn.row_factory = dict_row
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            init_schema()  # Local-demo bootstrap; use migrations for production.
            _pool = ConnectionPool(
                get_settings().database_url,
                min_size=1,
                max_size=8,
                configure=_configure,
                kwargs={"connect_timeout": 5, "options": "-c statement_timeout=10000"},
                timeout=5,
                open=True,
            )
        return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def connection() -> Iterator[psycopg.Connection]:
    with get_pool().connection() as conn:
        yield conn
