# Persistent Reasoning Engine — Engagement Reference (JOB-20260701155102-000126)

**Upwork:** https://www.upwork.com/jobs/~022072001960573380854
**Rate:** $150/hr (top of $80-150 band)
**Engagement:** 3-6 months, <30 hrs/wk, contract-to-hire

## What this is

A public-reference scaffold for the engagement. The production system we'd build lives in this shape:

```
src/
  schemas.py         # the 8 Pydantic enterprise-object schemas
  merge.py           # the ONLY writer to enterprise_state (architectural invariant)
  extract.py         # LLM extraction via raw SDKs + Pydantic-validated tool-calling
  parse.py           # PDF + HTML parsing
  edgar.py           # SEC EDGAR ingest
  api.py             # FastAPI query layer (state-as-of, changes, risks-active)
  schema.sql         # DDL for entities + source_documents + enterprise_state + transitions + review_queue
tests/
  conftest.py
  test_schemas.py
  test_merge.py
requirements.txt
```

## The architectural invariant

**Only `merge.py` writes to `enterprise_state`.**

The LLM extractor (`extract.py`) produces candidate updates. The merge function (`merge_fact()`) is the only place that:
- Acquires Postgres advisory locks per entity (serializes concurrent merges)
- Checks idempotency (same source_doc + source_section + entity writes once)
- Gates on confidence (below 0.6 → review_queue)
- Detects conflicts (new fact supersedes current → marks old valid_until)
- Records transitions (every change → enterprise_state_transitions)

This is what makes the system **persistent** rather than **stateless**.

## Stack

- **Python 3.12** + **FastAPI** for the query API
- **PostgreSQL 15** + (optional) **pgvector** + (optional) **Apache AGE** for graph queries
- **Raw OpenAI / Anthropic SDKs** for LLM extraction (NO LangChain)
- **Pydantic v2** for schema validation
- **pdfplumber** + **BeautifulSoup** for document parsing
- **httpx** for SEC EDGAR ingest
- **pytest** for tests

## The 8 enterprise-object schemas

The job description names 8 categories. Each is a Pydantic model in `src/schemas.py`:

| Category | Pydantic class | Purpose |
|---|---|---|
| Doctrine | `Doctrine` | Long-held beliefs / principles |
| Capabilities | `Capability` | What the enterprise can do (products, services, scale) |
| Active States | `ActiveState` | Current conditions |
| Active Obligations | `ActiveObligation` | Commitments (debt, lease, contract, regulatory) |
| Risks | `Risk` | Disclosed risks with severity |
| Management Decisions | `ManagementDecision` | Decisions + rationale + announce date |
| Causal Relationships | `CausalRelationship` | Links between facts |
| Enterprise Trajectory | `EnterpriseTrajectory` | Direction + evidence |

Every fact has:
- `valid_from: datetime`, `valid_until: Optional[datetime]` (temporal validity)
- `confidence: float ∈ [0, 1]` (LLM-assigned, gates below 0.6)
- `source_doc_id: int`, `source_section: str` (provenance)

## Run locally

```bash
pip install -r requirements.txt
createdb reasoning
psql reasoning < src/schema.sql
cd src && uvicorn api:app --reload
# → http://localhost:8000
```

For tests:

```bash
pytest tests/
```

## First deliverable (14-day prototype)

Ingest Microsoft + Amazon annual reports for 2022, 2023, 2024. Extract structured enterprise objects. Maintain persistent state across the 6 documents. Query the temporal-diff to show how Microsoft's risk profile evolved across the 3 years.

## Note on this being a public scaffold

This is the **pattern library**. The actual production system for a paying client lives in a private repo. What stays public is the architecture, the merge-step invariant, and the schema pattern. The Job-119 signal-pipeline scaffold (`9KMan/JOB-20260630010302-000119`) is the closest analog — same Pydantic + tool-call + idempotent-write patterns.
