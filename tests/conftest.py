"""pytest fixtures.

Two flavours of fixtures here:

1. `fact_dict` — sample data for schema tests.
2. `pg_conn` — a real Postgres connection against a dedicated test database.
   This is what lets `test_merge.py` exercise the *actual* `merge_fact`
   invariants (advisory locks, partial UNIQUE index, transition log) instead
   of mocking them away.

The test database (default `reasoning_test`) is created by hand from the
schema in `src/schema.sql`. Each test gets a fresh schema: we DROP+CREATE
the schema in a transaction-scoped fixture. No cross-test leakage.

Layered on top: in-memory entity seeds and a cursor factory stand-in so
unit tests that don't need a live Postgres connection can still exercise
the merge + api code paths.
"""
import os
import sys
import pathlib
import pytest
import psycopg2
import psycopg2.extras

# Make `import schemas, merge, api` work from tests without installing
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SCHEMA_SQL = (ROOT / "src" / "schema.sql").read_text()


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", "multica")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "multica")
PG_DB = os.environ.get("PG_DB", "reasoning_test")


@pytest.fixture(scope="session")
def pg_admin_conn():
    """One-time admin connection — creates the test database if needed."""
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname="multica",
        user=PG_USER, password=PG_PASSWORD,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (PG_DB,))
        if not cur.fetchone():
            cur.execute(f'CREATE DATABASE "{PG_DB}"')
    conn.close()
    return True


@pytest.fixture
def pg_conn(pg_admin_conn):
    """Fresh-schema Postgres connection per test.

    Strategy: open a connection, drop+recreate a private schema, run
    schema.sql in it, yield the connection, then drop the schema on
    teardown. Tests run their work in a transaction they ROLLBACK so
    state from one test doesn't bleed into the next.
    """
    test_schema = "reasoning_test_session"
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASSWORD,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
        cur.execute(f"CREATE SCHEMA {test_schema}")
        cur.execute(f"SET search_path TO {test_schema}")
        cur.execute(SCHEMA_SQL)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {test_schema} CASCADE")
        conn.close()


@pytest.fixture
def fact_dict():
    return {
        "valid_from": "2024-01-15T00:00:00Z",
        "valid_until": None,
        "confidence": 0.85,
        "source_doc_id": 1,
        "source_section": "Item 1. Business",
        "statement": "We are a cloud-first company.",
    }


# ---------------------------------------------------------------------------
# In-memory seed entities for the PoC — Microsoft + Amazon, FY22..FY24.
# These are the six filings referenced throughout SPEC.md.
# ---------------------------------------------------------------------------
SEED_ENTITIES = [
    ("MSFT", "Microsoft Corporation"),
    ("AMZN", "Amazon.com, Inc."),
]


@pytest.fixture
def seed_entities():
    """Return the canonical list of (ticker, name) tuples the seed step ingests."""
    return list(SEED_ENTITIES)


@pytest.fixture
def entity_rows():
    """In-memory entity rows with assigned ids — stand-in for `entities` table."""
    return [
        {"id": 1, "ticker": "MSFT", "name": "Microsoft Corporation"},
        {"id": 2, "ticker": "AMZN", "name": "Amazon.com, Inc."},
    ]


@pytest.fixture
def entity_row():
    """Single Microsoft row — convenience for tests that only need one entity."""
    return {"id": 1, "ticker": "MSFT", "name": "Microsoft Corporation"}


# ---------------------------------------------------------------------------
# Cursor factory — a minimal stand-in that records execute() calls.
# Lets unit tests assert what SQL merge.py / api.py would issue without
# spinning up a Postgres connection.
# ---------------------------------------------------------------------------
class _RecordingCursor:
    """Lightweight cursor stub.

    Implements the subset of psycopg2's cursor that merge.py + api.py touch:
      - execute(sql, params)
      - fetchone() / fetchall()
      - __enter__ / __exit__
    """

    def __init__(self):
        self.executed = []      # list of (sql, params) tuples
        self._fetch_one_queue = []   # pop-able queue of row dicts for fetchone()
        self._fetch_all_rows = []    # full result set for fetchall()
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def fetchone(self):
        if self._fetch_one_queue:
            return self._fetch_one_queue.pop(0)
        return None

    def fetchall(self):
        rows, self._fetch_all_rows = self._fetch_all_rows, []
        return rows

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


@pytest.fixture
def cursor_factory():
    """Return a factory that yields a fresh _RecordingCursor per call."""
    factory_calls = []

    def _factory():
        cur = _RecordingCursor()
        factory_calls.append(cur)
        return cur

    _factory.calls = factory_calls  # type: ignore[attr-defined]
    return _factory


@pytest.fixture
def cursor(cursor_factory):
    """A pre-built cursor for tests that only need one."""
    return cursor_factory()