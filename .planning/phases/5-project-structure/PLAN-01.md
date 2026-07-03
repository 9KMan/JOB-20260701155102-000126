# Phase 5: Project Structure

## Phase Goal
Single Python package `src/`, tests in `tests/`, fixtures for offline CI. No `app/` layout — keep it simple and aligned with the existing scaffold.

## Files to Create

```file:src/__init__.py
"""Persistent Reasoning Engine — main package."""
__version__ = "0.1.0"
```

```file:src/db.py
"""Connection helper — psycopg2 with RealDictCursor, context manager."""
```

```file:src/schemas.py
"""8 Pydantic enterprise-object schemas (FactBase + 8 subclasses)."""
```

```file:src/merge.py
"""merge_fact() — the ONLY writer to enterprise_state."""
```

```file:src/extract.py
"""LLM extractor — raw SDKs + Pydantic tool-calling."""
```

```file:src/parse.py
"""PDF (pdfplumber) + HTML (BeautifulSoup) parsers."""
```

```file:src/edgar.py
"""SEC EDGAR ingest — httpx with rate-limit semaphore."""
```

```file:src/api.py
"""FastAPI app — 4 endpoints + /health."""
```

```file:src/schema.sql
"""DDL — entities, source_documents, enterprise_state, transitions, review_queue."""
```

```file:src/seed.py
"""PoC seed — loads 6 pre-cached EDGAR filings (MSFT + AMZN FY22/23/24)."""
```

```file:tests/__init__.py
"""pytest test package."""
```

```file:tests/conftest.py
"""Shared fixtures — in-memory test entities + cursor against live Postgres."""
```

```file:tests/test_schemas.py
"""Schema validation tests — confidence bounds, Literal enums, required fields."""
```

```file:tests/test_merge.py
"""Merge invariants — advisory lock (mocked), idempotency, confidence gate,
conflict detection, transition log.
"""
```

```file:tests/test_api.py
"""FastAPI endpoint tests via TestClient — state, state-as-of, changes, risks-active."""
```

```file:tests/test_extract.py
"""Extractor tests with mocked OpenAI/Anthropic clients — schema validation
of tool-call args, malformed candidates skipped.
"""
```

```file:tests/test_parse.py
"""Parser tests — PDF and HTML fixture files."""
```

```file:tests/test_edgar.py
"""EDGAR tests with httpx mock — rate-limit handling, header injection."""
```

```file:tests/fixtures/msft_2024_10k_item1.html
"""Sample 10-K Item 1 HTML for parser tests."""
```

```file:tests/fixtures/amzn_2023_10k_item1a.html
"""Sample 10-K Item 1A HTML for parser tests."""
```

```file:pytest.ini
[pytest]
testpaths = tests
addopts = -v --tb=short
```

```file:README.md
# Persistent Reasoning Engine (JOB-20260701155102-000126)

Open-source reference scaffold for the Persistent Reasoning Engine engagement.
Architecture, merge-step invariant, and schema pattern are public. Production
deployment lives in a private repo per the Upwork contract.

![Architecture](./diagrams/architecture.svg)

## What this is
A system that ingests evolving public documents (SEC filings, annual reports,
shareholder letters) and maintains an evolving enterprise knowledge model over
time. The merge step (`src/merge.py`) is the architectural invariant — the ONLY
path that writes to persistent state.

## Stack
- Python 3.12 + FastAPI (sync handlers)
- PostgreSQL 15 with JSONB
- Raw OpenAI / Anthropic SDKs (no LangChain)
- Pydantic v2 for schemas + tool-calling
- pdfplumber + BeautifulSoup for parsing
- httpx for EDGAR ingest

## The 8 enterprise-object categories
Doctrine, Capability, ActiveState, ActiveObligation, Risk, ManagementDecision,
CausalRelationship, EnterpriseTrajectory. Each is a Pydantic model with
`valid_from`/`valid_until`/`confidence ∈ [0,1]`/`source_doc_id`/`source_section`.

## Run locally

```bash
pip install -r requirements.txt
createdb reasoning
psql reasoning < src/schema.sql
cd src && uvicorn api:app --reload
# → http://localhost:8000  ·  /docs for OpenAPI UI
```

## Tests

```bash
pytest tests/
```

## First deliverable
Ingest Microsoft + Amazon annual reports for FY22/23/24 (6 documents),
extract structured enterprise objects, query the temporal-diff to show how
each company's risk profile evolved across the 3 years.

## Built by
KMan / AI-Augmented Engineering Factory — MIT licensed.
```

## Done When
- `tree src tests` shows the layout above
- All 8 src/ files + 7 tests/ files exist
- `pytest tests/ --collect-only` enumerates ≥10 tests
- README embeds the SVG diagram (Bug 195 — file ref, not inline)
- `docker compose up` boots db + app, app returns 200 on /health