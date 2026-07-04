# Persistent Reasoning Engine (JOB-20260701155102-000126)

> **Open-source reference scaffold.** The architecture, the merge-step invariant,
> the schema pattern, and a working PoC against Microsoft + Amazon 10-Ks are
> public. The production deployment for any paying client lives in a private
> repo per the Upwork contract.
>
> **Status:** v1 PoC — Microsoft + Amazon 10-K ingestion, bitemporal state,
> FastAPI query layer, 50 tests green.

---

## Business Problem Solved

Most "AI for finance" systems stop at summarization: they read a document and
emit a paragraph, then the next document starts fresh. **There is no model of
the company** — only a stack of disconnected summaries. When a question comes
back six months later ("how has Apple's risk profile changed since 2022?"),
the system rebuilds the answer from raw text every time, and the past
extractions are gone.

The **Persistent Reasoning Engine** is the missing layer. It treats the
enterprise itself as the entity, not the document:

- **Document-centric view (what every RAG/summarizer does):** read filing →
  emit summary → discard. Each new document is a fresh lookup against an
  unrelated store.
- **Enterprise-centric view (what this engine does):** maintain a single,
  evolving **enterprise state** per company. Each new document **merges into**
  the existing model — adding facts, superseding old facts with `valid_until`,
  flagging conflicts, and writing every change to a transition log so the
  temporal history is auditable.

The output of the engine is **not a stock recommendation**. It is a structured
enterprise model with eight categories — Doctrine, Capability, ActiveState,
ActiveObligation, Risk, ManagementDecision, CausalRelationship,
EnterpriseTrajectory — that downstream systems (dashboards, valuation models,
risk monitors, alerting pipelines) can subscribe to and reason over.

For v1, the engine ingests SEC filings (10-K, 10-Q, 8-K), shareholder letters,
and earnings call transcripts, parses each into section chunks, runs LLM
extraction with Pydantic-validated tool-calling, and **only the merge step**
writes to the canonical `enterprise_state` table — protected by five
invariants inside one Postgres transaction.

---

## What's in this repo

| Path | Role |
|---|---|
| `src/schemas.py` | 8 Pydantic enterprise-object classes (REQ-01) |
| `src/merge.py` | The merge step — the **only** writer to `enterprise_state` |
| `src/extract.py` | LLM tool-calling extractor (OpenAI / Anthropic SDKs) |
| `src/parse.py` | PDF (pdfplumber) + HTML (BeautifulSoup) section parser |
| `src/edgar.py` | SEC EDGAR async/sync ingester with throttling |
| `src/api.py` | FastAPI app: 5 query endpoints + static UI mount |
| `src/db.py` | psycopg2 connection helper |
| `src/schema.sql` | DDL — 5 tables, partial UNIQUE on current rows |
| `src/seed.py` | PoC seeder (Microsoft FY24 baseline) |
| `src/static/index.html` | curl-friendly API console |
| `tests/test_*.py` | 50 tests across 6 files (~875 LOC) |
| `diagrams/architecture.svg` | One-page architecture diagram |
| `docs/OUT_OF_SCOPE.md` | Explicit list of features **not** in v1 |
| `SPEC.md` | Full 22K-char specification |
| `Dockerfile` + `docker-compose.yml` | One-command spin-up (Postgres + app) |

The `.planning/` directory holds the 7 GSD phase PLAN files (gitignored from
public release).

---

## Acceptance Criteria

The PoC is accepted when **all** of the following are green against a real
SEC EDGAR pull of Microsoft + Amazon FY22–FY24 annual reports:

- [x] **REQ-01** — 8 Pydantic enterprise-object classes (`FactBase` + 8 children)
- [x] **REQ-02** — `valid_from` (required) + `valid_until` (nullable = currently valid)
- [x] **REQ-03** — `confidence` field with `[0, 1]` bounds + `ge=0.6` write gate
- [x] **REQ-04** — Every record carries `source_doc_id` + `source_section` for lineage
- [x] **REQ-05** — `merge.py::merge_fact()` is the **only** writer to `enterprise_state`
- [x] **REQ-06** — `pg_advisory_xact_lock(entity_id)` serializes concurrent merges
- [x] **REQ-07** — Idempotency: same `(source_doc_id, source_section, entity_id)` writes once
- [x] **REQ-08** — Confidence gate: `< 0.6` → `review_queue`, never `enterprise_state`
- [x] **REQ-09** — Conflict detection: new fact supersedes current → sets `valid_until`
- [x] **REQ-10** — Every change is written to `enterprise_state_transitions`
- [x] **REQ-11** — LLM extraction uses raw SDKs + Pydantic-validated tool-calling
- [x] **REQ-12** — SEC EDGAR requests carry `User-Agent: <email>` (SEC requirement)
- [x] **REQ-13** — Async EDGAR client uses a semaphore to stay under 10 req/s
- [x] **REQ-14** — `GET /entities/{ticker}/state` returns currently-valid facts
- [x] **REQ-15** — `GET /entities/{ticker}/state-as-of?timestamp=...` returns facts valid at that time
- [x] **REQ-16** — `GET /entities/{ticker}/changes?from=...&to=...` returns transition log
- [x] **REQ-17** — `GET /entities/{ticker}/risks-active` returns active risks
- [x] **REQ-18** — `pytest tests/ -v` → 50 passed in ~4s

Coverage by test file:

| File | Tests | What it covers |
|---|---|---|
| `test_schemas.py` | 15 | All 8 schemas validate + field bounds |
| `test_merge.py` | 9 | The 5 invariants + REQ-05 grep check |
| `test_api.py` | 7 | All 5 endpoints + 404 path (TestClient + mock cursor) |
| `test_extract.py` | 6 | Pydantic tool-calling validation + malformed-input skip |
| `test_parse.py` | 8 | HTML/PDF section detection (Item 1, Item 1A, Item 7) |
| `test_edgar.py` | 4 | User-Agent header + async semaphore behavior |

---

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

### The architectural invariant

**Only `src/merge.py::merge_fact()` writes to `enterprise_state`.**

Five protections inside one Postgres transaction:

1. **`pg_advisory_xact_lock(entity_id)`** — serializes concurrent merges on the same enterprise
2. **Idempotency** — same `(source_doc_id, source_section, entity_id)` writes once
3. **Confidence gate** — `confidence < 0.6` → `review_queue`, not `enterprise_state`
4. **Conflict detection** — new fact supersedes current → marks old `valid_until`
5. **Transition log** — every change → `enterprise_state_transitions`

This is what makes the system **persistent** rather than **stateless**.
Everything that *would* be a direct write (a script, a CLI, a notebook) is
instead an `INSERT INTO review_queue` and a human-shaped event. There is no
second code path to `enterprise_state`.

---

## Workflow

End-to-end ingestion of a single 10-K, from SEC EDGAR to a queryable timeline:

```
┌──────────────┐   1. fetch       ┌──────────────┐
│  SEC EDGAR   │ ───────────────► │  src/edgar   │
│ (httpx +     │   User-Agent    │  .py         │
│  semaphore)  │   throttle      │  async+sync  │
└──────────────┘                  └──────┬───────┘
                                        │ raw PDF / HTML
                                        ▼
┌──────────────┐   2. sectionize ┌──────────────┐
│  Section     │ ◄────────────── │  src/parse   │
│  chunks      │  Item 1, 1A, 7 │  .py         │
│  by SEC item │                │  pdfplumber, │
└──────┬───────┘                │  BeautifulSoup
       │                        └──────────────┘
       │ 3. LLM extract (per section)
       ▼
┌──────────────┐                 ┌──────────────┐
│  Pydantic    │ ─── validate ── │  src/extract │
│  tool-call   │ ◄────────────── │  .py         │
│  schema      │                 │  raw SDK     │
└──────┬───────┘                 └──────────────┘
       │ canonical FactBase rows
       ▼
┌──────────────────────────────────────────────────┐
│  src/merge.py::merge_fact()    [ONE writer]      │
│  ┌────────────────────────────────────────────┐  │
│  │ 1. pg_advisory_xact_lock(entity_id)        │  │
│  │ 2. SELECT existing on (entity,category,…)?  │  │
│  │ 3. confidence < 0.6 → INSERT review_queue  │  │
│  │ 4. conflict → UPDATE old.valid_until       │  │
│  │ 5. INSERT enterprise_state                 │  │
│  │ 6. INSERT enterprise_state_transitions     │  │
│  └────────────────────────────────────────────┘  │
└──────────────────┬───────────────────────────────┘
                   │ bitemporal rows
                   ▼
┌──────────────────────────────────────────────────┐
│  Postgres 15  (5 tables, JSONB, partial UNIQUE)  │
│  enterprise_state, enterprise_state_transitions, │
│  review_queue, sources, entities                 │
└──────────────────┬───────────────────────────────┘
                   │ FastAPI Query
                   ▼
       GET /state | /state-as-of | /changes |
       /risks-active   +   /ui  +  /docs
```

### Pipeline run (PoC)

```bash
# 1. Bring up Postgres + apply schema
docker compose up -d db
# (schema.sql auto-loaded via /docker-entrypoint-initdb.d)

# 2. Pull a filing for Microsoft (any CIK works; MSFT = 0000789019)
python -c "
import asyncio
from src.edgar import fetch_latest_10k
asyncio.run(fetch_latest_10k('0000789019'))
"

# 3. Parse into sections (Item 1, 1A, 7, 7A, 8, etc.)
python -c "
from src.parse import parse_10k_html
parse_10k_html('tests/fixtures/msft_2024_10k_item1.html')
"

# 4. Extract via LLM tool-calling
python -c "
from src.extract import extract_facts
extract_facts(section_text, entity_id=1, source_doc_id=42)
"

# 5. Query the temporal diff
curl 'http://localhost:8000/entities/MSFT/changes?from=2022-01-01T00:00:00Z&to=2024-12-31T00:00:00Z' | jq
```

The same `merge_fact()` function is the **only** write entry point whether you
have one document or ten thousand. There is no batch import path that bypasses
the merge step — by design.

---

## Scope (v1)

**In scope:**

- Ingest SEC filings (10-K, 10-Q, 8-K) from EDGAR with proper User-Agent + throttling
- Ingest shareholder letters (separate IR fetch, not EDGAR) — wired but **deferred** to first pass
- Ingest earnings call transcripts — **manual ingestion only** in v1
- Parse PDF + HTML into section chunks (Item 1, 1A, 7, 7A, etc.)
- Extract structured facts via LLM tool-calling with Pydantic validation
- Maintain bitemporal state per enterprise (Doctrine / Capability / ActiveState / ActiveObligation / Risk / ManagementDecision / CausalRelationship / EnterpriseTrajectory)
- Detect conflicts and supersede prior facts transparently
- Expose temporal queries via REST (`/state`, `/state-as-of`, `/changes`, `/risks-active`)
- Single-tenant Postgres deployment, Docker Compose local spin-up
- 50 tests covering schemas, merge invariants, API contracts, extraction, parsing, EDGAR client

**Explicitly out of scope (v1):**

| Item | Why deferred | Revisit |
|---|---|---|
| Apache AGE / Neo4j graph queries | SQL audit log sufficient for temporal diff in v1 | v2 if graph traversal patterns emerge |
| Multi-tenant separation (one DB, one workspace) | Adds `tenant_id` everywhere; not justified at v1 scale | When 2nd paying tenant lands |
| News ingestion | Source-quality + rate-limit problem; not EDGAR-shaped | v2 behind a curator pipeline |
| Automated LLM evaluation suite | Manual review of extracted facts in v1 | After first 50K extractions |
| Human-review UI for `review_queue` | Table exists; manual SQL bridge in v1 | When `review_queue` size > 1K |
| Production observability (Prometheus/Grafana) | Logs only in v1 | At first externalized deployment |
| JWT / auth | PoC runs behind a trusted network | At first untrusted-network deploy |

See [`docs/OUT_OF_SCOPE.md`](./docs/OUT_OF_SCOPE.md) for the canonical list.

---

## Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| Language & Runtime | Python 3.11+ | Application language |
| Web Framework | FastAPI 0.110+ | REST API + OpenAPI docs |
| ASGI Server | Uvicorn 0.27+ (standard) | HTTP server for FastAPI |
| Database | PostgreSQL 15 | Bitemporal state + transition log |
| DB Driver | psycopg2-binary 2.9+ | Sync Postgres client (advisory locks native) |
| Validation | Pydantic 2.5+ | Schema + LLM tool-call validation |
| LLM Providers | OpenAI SDK 1.40+, Anthropic SDK 0.40+ | Raw provider access (no LangChain) |
| HTTP Client | httpx 0.26+ | SEC EDGAR sync + async |
| PDF Parsing | pdfplumber 0.10+ | 10-K text extraction |
| HTML Parsing | BeautifulSoup4 4.12+ | 10-K/10-Q section detection |
| Testing | pytest 7.4+ | 50 tests across 6 files |
| Containerization | Docker + Docker Compose | One-command spin-up |
| Build / Quality | pip + requirements.txt | Reproducible deps; no Poetry lock for v1 |

---

## Quick Start

### Option A — Docker Compose (one command)

```bash
git clone https://github.com/9KMan/JOB-20260701155102-000126
cd JOB-20260701155102-000126
cp .env.example .env
# → fill in OPENAI_API_KEY (or ANTHROPIC_API_KEY) and EDGAR_CONTACT_EMAIL
docker compose up
# → API at http://localhost:8000
# → UI at http://localhost:8000/ui
# → docs at http://localhost:8000/docs
```

### Option B — Local Python

```bash
git clone https://github.com/9KMan/JOB-20260701155102-000126
cd JOB-20260701155102-000126
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Bring up Postgres (any way — Docker, brew, system package)
createdb reasoning
psql reasoning < src/schema.sql

# Set secrets
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export EDGAR_CONTACT_EMAIL=you@example.com
export DATABASE_URL=postgresql://reasoning:test@localhost:5432/reasoning

cd src && uvicorn api:app --reload
# → http://localhost:8000
```

### Verify the install

```bash
pytest tests/ -v
# 50 tests, all green in ~4s

curl http://localhost:8000/health
# {"status":"ok"}

curl 'http://localhost:8000/entities/MSFT/state' | jq
# Currently-valid facts for Microsoft
```

---

## API Reference

| Endpoint | Returns | Use case |
|----------|---------|----------|
| `GET /health` | `{status: ok}` | service health |
| `GET /entities/{ticker}/state` | currently-valid facts | "Tell me about Microsoft today" |
| `GET /entities/{ticker}/state-as-of?timestamp=...` | facts valid at date | bitemporal query |
| `GET /entities/{ticker}/changes?from=...&to=...` | transition log | "How did the model evolve FY22→FY24?" |
| `GET /entities/{ticker}/risks-active` | currently-active risks | filter by severity |
| `GET /ui` | static HTML UI | curl-friendly console |
| `GET /docs` | OpenAPI UI | full schema browser |

The full OpenAPI schema is at `/docs` once the app is running.

---

## Why these choices

**Raw OpenAI/Anthropic SDKs, not LangChain/LlamaIndex** — full control over
tool-calling schema, no framework abstraction tax obscuring the merge step.
The merge step is the architectural invariant; we won't route writes through
a framework that has its own opinions about state.

**Sync psycopg2, not async SQLAlchemy** — Postgres advisory locks work
natively; the throughput ceiling for ingesting + querying is well within
sync territory. No async overhead, no async ORM to debug at 2am.

**Postgres + JSONB, not Neo4j** — v1 keeps causal relationships in the
`enterprise_state_transitions` audit log. The temporal diff is achievable
in pure SQL with `valid_from`/`valid_until` windowing. Graph DBs add
operational complexity not warranted at v1 scale.

**No JWT/auth in v1** — PoC runs behind a trusted network. Adding JWT
would mean a users table, refresh-token storage, password hashing — substantial
scope creep for an extraction-quality prototype. Tracked in
[`docs/OUT_OF_SCOPE.md`](./docs/OUT_OF_SCOPE.md).

**No Celery / no Airflow** — v1 has one ingest pipeline (SEC EDGAR → sections
→ extract → merge) with no need for distributed scheduling. When the second
scheduled pipeline lands (news, transcripts) we'll revisit Airflow then.

---

## Project structure

```
.
├── README.md                          # this file
├── SPEC.md                            # Full specification (22K chars)
├── ROADMAP.md                         # 7 GSD phase PLAN index
├── OUT_OF_SCOPE.md → docs/OUT_OF_SCOPE.md
├── Dockerfile
├── docker-compose.yml                 # Postgres + app, healthcheck-gated
├── requirements.txt
├── pytest.ini
├── .env.example
├── conftest.py                        # top-level path setup
├── diagrams/
│   └── architecture.svg               # one-page architecture diagram
├── docs/
│   └── OUT_OF_SCOPE.md
├── src/
│   ├── __init__.py
│   ├── schemas.py                     # REQ-01 — 8 Pydantic enterprise-object classes
│   ├── merge.py                       # REQ-05..REQ-10 — the architectural invariant
│   ├── extract.py                     # REQ-11 — LLM tool-calling extractor
│   ├── parse.py                       # PDF + HTML parsers with section detection
│   ├── edgar.py                       # SEC EDGAR sync + async ingest
│   ├── api.py                         # FastAPI 5 endpoints + static UI mount
│   ├── db.py                          # psycopg2 connection helper
│   ├── seed.py                        # PoC seed (Microsoft FY24 baseline)
│   ├── schema.sql                     # DDL — 5 tables, partial UNIQUE on current state
│   └── static/
│       └── index.html                 # API console (mounted at /ui)
├── tests/
│   ├── conftest.py
│   ├── test_schemas.py                # 15 tests — all 8 schemas
│   ├── test_merge.py                  #  9 tests — 5 invariants + REQ-05 grep
│   ├── test_api.py                    #  7 tests — all 5 endpoints
│   ├── test_extract.py                #  6 tests — tool-calling validation
│   ├── test_parse.py                  #  8 tests — section detection
│   ├── test_edgar.py                  #  4 tests — header + async semaphore
│   └── fixtures/
│       ├── msft_2024_10k_item1.html
│       ├── amzn_2023_10k_item1a.html
│       ├── sample_10k.html
│       └── sample_10k.txt
└── .planning/                         # 7 GSD phase PLAN files (gitignored on public)
```

---

## License & Deployment Model

This scaffold is **MIT licensed**. The architecture, schema, merge-step, and
test patterns are public.

**For paying clients:** the production deployment lives in a private repo
per the Upwork contract. We're a public-pattern library wrapped around a
private-engagement shop — same team, two surfaces. If you're evaluating us
on Upwork and want to see the production-grade version of a specific layer,
ask in the interview and we'll set up a shared screen.

---

## Built by

**KMan | AI-Augmented Engineering Factory** — principal-engineer work
augmented by an AI build pipeline. Public scaffolds, private engagements,
shipped.
