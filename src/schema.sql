-- Persistent Reasoning Engine — DDL
-- This is the canonical schema; section 6.1 of the proposal.

CREATE TABLE entities (
    id          SERIAL PRIMARY KEY,
    ticker      TEXT UNIQUE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE source_documents (
    id              SERIAL PRIMARY KEY,
    entity_id       INT REFERENCES entities(id),
    title           TEXT NOT NULL,
    filing_date     DATE,
    document_type   TEXT,  -- '10-K', '10-Q', '8-K', 'shareholder_letter', 'earnings_transcript', etc.
    accession_no    TEXT,  -- SEC EDGAR accession number (for filings)
    version         INT DEFAULT 1,
    raw_text        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(entity_id, document_type, filing_date, version)
);

CREATE INDEX source_documents_entity_idx ON source_documents(entity_id);

CREATE TABLE enterprise_state (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       INT NOT NULL REFERENCES entities(id),
    category        TEXT NOT NULL,    -- 'doctrine', 'capability', 'active_state', etc.
    fact_json       JSONB NOT NULL,
    valid_from      TIMESTAMPTZ NOT NULL,
    valid_until     TIMESTAMPTZ,       -- NULL = currently valid
    confidence      NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source_doc_id   INT NOT NULL REFERENCES source_documents(id),
    source_section  TEXT NOT NULL
);

CREATE INDEX enterprise_state_entity_idx ON enterprise_state(entity_id, category);
CREATE INDEX enterprise_state_valid_idx ON enterprise_state(valid_from, valid_until);

-- REQ-05 architectural invariant, DB-enforced: at most ONE currently-valid row
-- per (entity_id, category). Historical rows (valid_until IS NOT NULL) are
-- exempt — the temporal table accumulates superseded facts.
-- This is a safety net: even if application logic somehow attempts a second
-- concurrent INSERT of a current row, Postgres rejects it.
CREATE UNIQUE INDEX enterprise_state_one_current_per_category
    ON enterprise_state(entity_id, category)
    WHERE valid_until IS NULL;

-- Audit log of every state change. This is what makes the temporal-diff query possible.
CREATE TABLE enterprise_state_transitions (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       INT NOT NULL REFERENCES entities(id),
    category        TEXT NOT NULL,
    prev_state_id   BIGINT REFERENCES enterprise_state(id),
    new_state_id    BIGINT REFERENCES enterprise_state(id),
    source_doc_id   INT NOT NULL REFERENCES source_documents(id),
    source_section  TEXT NOT NULL,    -- SPEC §4.4: provenance for the audit log
    transition_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX transitions_entity_idx ON enterprise_state_transitions(entity_id, transition_at);

-- Review queue: low-confidence or malformed candidates land here for human review
CREATE TABLE review_queue (
    id              BIGSERIAL PRIMARY KEY,
    entity_id       INT NOT NULL REFERENCES entities(id),
    fact_json       JSONB,
    reason          TEXT NOT NULL,   -- 'low_confidence', 'malformed', 'unknown_entity'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT
);
