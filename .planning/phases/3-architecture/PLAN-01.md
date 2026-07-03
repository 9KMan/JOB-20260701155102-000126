# Phase 3: Architecture

## Phase Goal
Five-layer architecture: Ingest → Parse → Extract → Merge → Query, with `merge.py` as the architectural invariant (only writer to `enterprise_state`).

```
+-------------------+     +----------+     +----------+     +-----------+     +-----------+
| Ingest (EDGAR)    | --> | Parse    | --> | Extract  | --> | Merge     | --> | Query     |
| edgar.py          |     | parse.py |     | extract.py|    | merge.py  |     | api.py    |
| httpx async       |     | pdf/html |     | raw SDKs |     | ONLY      |     | FastAPI   |
| rate-limit safe   |     |          |     | +Pydantic|     | writer    |     | sync      |
+-------------------+     +----------+     +----------+     +-----------+     +-----------+
                                                                       |
                                                                       v
                                                          +-------------------------+
                                                          | PostgreSQL 15 (JSONB)   |
                                                          | entities                |
                                                          | source_documents        |
                                                          | enterprise_state        |
                                                          | enterprise_state_trans  |
                                                          | review_queue            |
                                                          +-------------------------+
```

## Files to Create

```file:src/__init__.py
"""Persistent Reasoning Engine — main package."""
```

```file:src/schemas.py
"""8 enterprise-object Pydantic schemas — Doctrine, Capability, ActiveState,
ActiveObligation, Risk, ManagementDecision, CausalRelationship,
EnterpriseTrajectory. Each inherits FactBase (valid_from, valid_until,
confidence ∈ [0,1], source_doc_id, source_section).
"""
```

```file:src/merge.py
"""Architectural invariant: ONLY merge_fact() writes to enterprise_state.

Five protections:
1. pg_advisory_xact_lock(entity_id) — serialize concurrent merges
2. Idempotency check via enterprise_state_transitions
3. Confidence gate: confidence < 0.6 → review_queue
4. Conflict detection: supersede current fact in same category
5. Transition log: every state change recorded
"""
```

```file:src/extract.py
"""LLM extractor — raw OpenAI/Anthropic SDKs with Pydantic tool-calling.
Produces candidates; merge step applies them. Never writes to DB.
"""
```

```file:src/parse.py
"""PDF (pdfplumber) + HTML (BeautifulSoup) parsers. Returns section chunks
for LLM extraction. Naive page-level parsing for v1.
"""
```

```file:src/edgar.py
"""SEC EDGAR ingest — fetches 10-K/10-Q/8-K filings via httpx.
Respects 10 req/sec rate limit. Requires EDGAR_CONTACT_EMAIL env var.
"""
```

```file:src/api.py
"""FastAPI query layer (sync handlers, sync psycopg2).
Endpoints:
- GET /entities/{ticker}/state              (currently-valid)
- GET /entities/{ticker}/state-as-of        (bitemporal)
- GET /entities/{ticker}/changes            (temporal diff)
- GET /entities/{ticker}/risks-active       (filter by severity)
- GET /health
"""
```

```file:src/schema.sql
"""DDL — entities, source_documents, enterprise_state,
enterprise_state_transitions, review_queue. UNIQUE constraint on
source_documents for idempotent ingest.
"""
```

```file:src/seed.py
"""PoC seed: ingest Microsoft + Amazon 10-Ks for FY22/23/24 (6 documents).
Uses fixture data (pre-cached EDGAR JSON) so tests don't hit SEC.
"""
```

## Done When
- All 8 source files exist under src/
- `from src.api import app` works in Python
- `psql reasoning < src/schema.sql` creates 5 tables
- No file imports `sqlalchemy` or `langchain` or `llama_index`
- `merge.py` is the only file that contains `INSERT INTO enterprise_state`