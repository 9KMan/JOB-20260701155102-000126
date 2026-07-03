# Phase 4: Data Model

## Phase Goal
Five tables. Bitemporal state in `enterprise_state`. Audit trail in `enterprise_state_transitions`. Idempotent ingest via UNIQUE constraint on `source_documents`.

## Files to Create

```file:src/schema.sql
-- Persistent Reasoning Engine — DDL

CREATE TABLE entities (
    id          SERIAL PRIMARY KEY,
    ticker      TEXT UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTOGTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE source_documents (
    id              SERIAL PRIMARY KEY,
    entity_id       INT REFERENCES entities(id),
    title           TEXT NOT NULL,
    filing_date     DATE,
    document_type   TEXT,  -- '10-K','10-Q','8-K','shareholder_letter','earnings_transcript'
    accession_no    TEXT,  -- SEC EDGAR accession number
    version         INT DEFAULT 1,
    raw_text        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(entity_id, document_type, filing_date, version)
);
CREATE INDEX source_documents_entity_idx ON source_documents(entity_id);

CREATE TABLE enterprise_state (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       INT NOT NULL REFERENCES entities(id),
    category        TEXT NOT NULL,  -- 'doctrine','capability','active_state','active_obligation','risk','management_decision','causal_relationship','enterprise_trajectory'
    fact_json       JSONB NOT NULL,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_until     TIMESTAMPTZ,     -- NULL = currently valid
    confidence      NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source_doc_id   INT NOT NULL REFERENCES source_documents(id),
    source_section  TEXT NOT NULL
);
CREATE INDEX enterprise_state_entity_idx ON enterprise_state(entity_id, category);
CREATE INDEX enterprise_state_valid_idx  ON enterprise_state(valid_from, valid_until);
CREATE UNIQUE INDEX enterprise_state_current_idx
    ON enterprise_state(entity_id, category) WHERE valid_until IS NULL;

CREATE TABLE enterprise_state_transitions (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       INT NOT NULL REFERENCES entities(id),
    category        TEXT NOT NULL,
    prev_state_id   BIGINT REFERENCES enterprise_state(id),
    new_state_id    BIGINT REFERENCES enterprise_state(id),
    source_doc_id   INT NOT NULL REFERENCES source_documents(id),
    transition_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX transitions_entity_idx ON enterprise_state_transitions(entity_id, transition_at);

CREATE TABLE review_queue (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       INT NOT NULL REFERENCES entities(id),
    fact_json       JSONB,
    reason          TEXT NOT NULL,  -- 'low_confidence','malformed','unknown_entity'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT
);
```

```file:src/db.py
"""Connection helper — psycopg2 with RealDictCursor, context-manager protocol.
Single open()/close() per request via FastAPI dependency.
"""
import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

def connection_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://reasoning:test@localhost:5432/reasoning")

@contextmanager
def get_cursor():
    conn = psycopg2.connect(connection_url(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn, conn.cursor() as cur:
            yield cur
    finally:
        conn.close()
```

## Done When
- `psql reasoning < src/schema.sql` creates 5 tables
- `enterprise_state_current_idx` is a partial UNIQUE — only one currently-valid row per (entity_id, category)
- `src/db.py::get_cursor()` is a working context manager
- DDL includes FK constraints to source_documents (REQ-04)