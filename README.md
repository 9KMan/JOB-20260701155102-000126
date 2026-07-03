# Persistent Reasoning Engine (JOB-20260701155102-000126)

Open-source reference scaffold for the Persistent Reasoning Engine engagement.
Architecture, merge-step invariant, and schema pattern are public. Production
deployment lives in a private repo per the Upwork contract.

**Status:** v1 PoC — Microsoft + Amazon 10-K ingestion, bitemporal state, FastAPI query layer.

## Architecture

![Architecture](./diagrams/architecture.svg)

Five layers, each with one responsibility:

| Layer | Component | Responsibility |
|-------|-----------|----------------|
| Ingest | `src/edgar.py` | Pull SEC filings via httpx (sync + async variants) |
| Parse | `src/parse.py` | PDF (pdfplumber) + HTML (BeautifulSoup) → section chunks |
| Extract | `src/extract.py` | Raw OpenAI/Anthropic SDKs + Pydantic-validated tool-calling |
| Merge | `src/merge.py` | **The ONLY writer to `enterprise_state`** (5 invariants) |
| Query | `src/api.py` | FastAPI: state / state-as-of / changes / risks-active |

## The architectural invariant

**Only `src/merge.py::merge_fact()` writes to `enterprise_state`.**

Five protections inside one Postgres transaction:

1. **`pg_advisory_xact_lock(entity_id)`** — serializes concurrent merges on the same enterprise
2. **Idempotency** — same `(source_doc_id, source_section, entity_id)` writes once
3. **Confidence gate** — `confidence < 0.6` → `review_queue`, not `enterprise_state`
4. **Conflict detection** — new fact supersedes current → marks old `valid_until`
5. **Transition log** — every change → `enterprise_state_transitions`

This is what makes the system **persistent** rather than **stateless**.

## The 8 enterprise-object categories

Doctrine, Capability, ActiveState, ActiveObligation, Risk, ManagementDecision,
CausalRelationship, EnterpriseTrajectory. Each is a Pydantic model in
`src/schemas.py` inheriting from `FactBase`:

```python
class FactBase(BaseModel):
    valid_from: datetime
    valid_until: Optional[datetime] = None   # NULL = currently valid
    confidence: float = Field(ge=0, le=1)   # gates below 0.6 → review_queue
    source_doc_id: int
    source_section: str                     # e.g. "Item 1A. Risk Factors"
```

## API

| Endpoint | Returns | Use case |
|----------|---------|----------|
| `GET /health` | `{status: ok}` | service health |
| `GET /entities/{ticker}/state` | currently-valid facts | "Tell me about Microsoft today" |
| `GET /entities/{ticker}/state-as-of?timestamp=...` | facts valid at date | bitemporal query |
| `GET /entities/{ticker}/changes?from=...&to=...` | transition log | "How did the model evolve FY22→FY24?" |
| `GET /entities/{ticker}/risks-active` | currently-active risks | filter by severity |
| `GET /ui` | static HTML UI | curl-friendly console |
| `GET /docs` | OpenAPI UI | full schema browser |

## Run locally

### Option A — Docker Compose (one command)

```bash
docker compose up
# → API at http://localhost:8000
# → UI at http://localhost:8000/ui
# → docs at http://localhost:8000/docs
```

### Option B — Local Python

```bash
pip install -r requirements.txt
createdb reasoning
psql reasoning < src/schema.sql
cd src && uvicorn api:app --reload
# → http://localhost:8000
```

Set env vars in `.env` (see `.env.example`):

```bash
DATABASE_URL=postgresql://reasoning:test@localhost:5432/reasoning
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
EDGAR_CONTACT_EMAIL=your-email@example.com   # SEC requires a real email
```

## Tests

```bash
pytest tests/ -v
# 50 tests, all green in ~4s
# Coverage:
#   - test_schemas.py: all 8 Pydantic schemas validate
#   - test_merge.py:    5 invariants of merge_fact (mock cursor)
#   - test_api.py:      5 endpoints + 404 path (TestClient + mock)
#   - test_extract.py:  Pydantic tool-calling + malformed skip
#   - test_parse.py:    HTML/PDF section detection
#   - test_edgar.py:    User-Agent header + async semaphore
```

## First deliverable (PoC)

Ingest Microsoft + Amazon annual reports for FY22, FY23, FY24 (6 documents).
Extract structured enterprise objects. Maintain persistent state across years.
Query the temporal-diff to show how each company's risk profile evolved:

```bash
curl 'http://localhost:8000/entities/MSFT/changes?from=2022-01-01T00:00:00Z&to=2024-12-31T00:00:00Z' | jq
```

## Project structure

```
.
├── README.md
├── SPEC.md                  # Full specification (22K chars)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
├── .env.example
├── conftest.py              # Top-level path setup
├── docs/
│   └── OUT_OF_SCOPE.md
├── diagrams/
│   └── architecture.svg
├── src/
│   ├── __init__.py
│   ├── schemas.py           # REQ-01 — 8 Pydantic enterprise-object classes
│   ├── merge.py             # REQ-05..REQ-10 — the architectural invariant
│   ├── extract.py           # REQ-11 — LLM tool-calling extractor
│   ├── parse.py             # PDF + HTML parsers with section detection
│   ├── edgar.py             # SEC EDGAR sync + async ingest
│   ├── api.py               # FastAPI 5 endpoints + static UI mount
│   ├── db.py                # psycopg2 connection helper
│   ├── seed.py              # PoC seed for MSFT FY22 10-K
│   ├── schema.sql           # DDL — 5 tables, partial UNIQUE on current state
│   └── static/
│       └── index.html       # API console (mounted at /ui)
├── tests/
│   ├── conftest.py
│   ├── test_schemas.py      # 15 tests — all 8 schemas
│   ├── test_merge.py        #  9 tests — 5 invariants + REQ-05 grep
│   ├── test_api.py          #  7 tests — all 5 endpoints
│   ├── test_extract.py      #  6 tests — tool-calling validation
│   ├── test_parse.py        #  8 tests — section detection
│   ├── test_edgar.py        #  4 tests — header + async semaphore
│   └── fixtures/
│       ├── msft_2024_10k_item1.html
│       └── amzn_2023_10k_item1a.html
└── .planning/               # 7 GSD phase PLAN files (gitignored on public)
```

## Why these choices

**Raw OpenAI/Anthropic SDKs, not LangChain/LlamaIndex** — full control over
tool-calling schema, no framework abstraction tax obscuring the merge step.

**Sync psycopg2, not async SQLAlchemy** — Postgres advisory locks work
natively; the throughput ceiling for ingesting + querying is well within
sync territory. No async overhead.

**Postgres + JSONB, not Neo4j** — v1 keeps causal relationships in the
`enterprise_state_transitions` audit log. The temporal diff is achievable
in pure SQL. Graph DBs add operational complexity not warranted at v1 scale.

**No JWT/auth in v1** — PoC runs behind a trusted network. Adding JWT
would mean a users table, refresh-token storage, password hashing — substantial
scope creep for an extraction-quality prototype.

See [docs/OUT_OF_SCOPE.md](./docs/OUT_OF_SCOPE.md) for the full list of
deferred items and when to revisit them.

## Built by

**KMan / AI-Augmented Engineering Factory** — MIT licensed. Production
deployment for paying clients lives in a private repo per the Upwork
contract; this scaffold is the public pattern library.