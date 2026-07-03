"""Database access layer — psycopg2 connection helper.

Single responsibility: open a Postgres connection from DATABASE_URL and yield
a RealDictCursor inside a transaction.

Why RealDictCursor: every consumer (merge.py, api.py, seed.py) treats rows as
dicts keyed on column name. RealDictCursor avoids the brittle index access
that breaks the moment a SELECT adds a column.

Usage:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM entities WHERE ticker = %s", ("MSFT",))
        row = cur.fetchone()        # dict-like

The context manager commits on clean exit and rolls back on exception, then
always closes the connection. This is the pattern the merge step relies on
(advisory locks are released by COMMIT/ROLLBACK, not by cursor.close()).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

import psycopg2
import psycopg2.extras


def _resolve_dsn() -> str:
    """Return the Postgres DSN from the environment.

    Falls back to the docker-compose default so unit tests that import db.py
    without a real DB still get a usable DSN string. The connection itself
    is lazy — _resolve_dsn() never opens a socket.
    """
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://reasoning:test@localhost:5432/reasoning",
    )


def connect():
    """Open a new Postgres connection with RealDictCursor as the default."""
    return psycopg2.connect(
        _resolve_dsn(),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


@contextmanager
def get_cursor() -> Generator[Any, None, None]:
    """Yield a RealDictCursor inside a transaction.

    - Commits on clean exit.
    - Rolls back on any exception.
    - Always closes the connection.

    This is the canonical way every other module in `src/` touches the DB.
    Merge (merge.merge_fact) depends on the transaction boundary: advisory
    locks acquired by pg_advisory_xact_lock() are released at COMMIT or
    ROLLBACK, which is exactly when this context manager returns.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()