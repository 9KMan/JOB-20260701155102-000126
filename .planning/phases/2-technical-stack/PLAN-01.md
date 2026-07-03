# Phase 2: Technical Stack

## Phase Goal
Lock the production stack to match the existing scaffold: synchronous psycopg2 (NOT async SQLAlchemy), raw OpenAI/Anthropic SDKs (NOT LangChain), Pydantic v2 schemas, FastAPI sync handlers. Document why each choice was made so future contributors don't drift.

## Tech Stack (final, with justifications)

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.12 | Pattern matching, perf, current LTS |
| Web framework | FastAPI 0.110+ (sync handlers) | OpenAPI for free; sync handlers match sync DB driver |
| DB driver | psycopg2-binary 2.9+ (sync) | Postgres advisory locks work natively; no async overhead for our throughput |
| DB | PostgreSQL 15 (JSONB for fact payload) | Bitemporal queries + advisory locks + JSONB in one engine |
| Schemas | Pydantic v2 (model_json_schema()) | Strict validation + auto-generated tool-calling schemas |
| LLM SDKs | openai>=1.40, anthropic>=0.40 (raw) | Full control over tool-call shape; no framework abstraction tax |
| PDF parsing | pdfplumber 0.10+ | Reliable text extraction from 10-K filings |
| HTML parsing | beautifulsoup4 4.12+ | Standard for EDGAR HTML filings |
| HTTP | httpx 0.26+ | Async-capable (used for EDGAR rate-limit handling) |
| Tests | pytest 7.4+ | Standard |
| Container | python:3.12-slim | ~150MB final image |

**NOT used:** LangChain / LlamaIndex (abstraction tax obscures merge step), SQLAlchemy ORM (manual SQL gives clearer audit log), pgvector (PoC doesn't need semantic dedup), JWT auth (no auth in PoC).

## Files to Create

```file:requirements.txt
fastapi>=0.110,<1.0
uvicorn[standard]>=0.27,<1.0
psycopg2-binary>=2.9,<3.0
pydantic>=2.5,<3.0
openai>=1.40,<2.0
anthropic>=0.40,<1.0
httpx>=0.26,<1.0
pdfplumber>=0.10,<1.0
beautifulsoup4>=4.12,<5.0
pytest>=7.4,<8.0
```

```file:.env.example
# Database
DATABASE_URL=postgresql://reasoning:test@localhost:5432/reasoning

# LLM providers (at least one required)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# SEC EDGAR requires a real contact email
EDGAR_CONTACT_EMAIL=your-email@example.com
```

```file:Dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
WORKDIR /app/src
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

```file:docker-compose.yml
version: "3.8"
services:
  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: reasoning
      POSTGRES_PASSWORD: test
      POSTGRES_DB: reasoning
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./src/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U reasoning -d reasoning"]
      interval: 5s
      timeout: 3s
      retries: 10
  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: "postgresql://reasoning:test@db:5432/reasoning"
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY:-}"
      OPENAI_API_KEY: "${OPENAI_API_KEY:-}"
      EDGAR_CONTACT_EMAIL: "${EDGAR_CONTACT_EMAIL:-dev@example.com}"
    ports:
      - "8000:8000"
volumes:
  pgdata:
```

## Done When
- `pip install -r requirements.txt` succeeds
- `docker compose up` brings up Postgres + app, app connects to db
- `.env.example` documents all env vars actually read by code
- No SQLAlchemy / LangChain imports anywhere in src/