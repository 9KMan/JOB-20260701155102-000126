# Out of Scope (v1)

This document mirrors section 12 of [SPEC.md](../SPEC.md). It is the canonical
list of features explicitly **not** included in v1 so we don't get scope-crept
during client reviews.

## 12. Out of scope (v1)

- Shareholder letters (separate IR fetch, not EDGAR)
- Earnings call transcripts (manual ingestion only in v1)
- News ingestion (rate limits + source quality are a v2 problem)
- Apache AGE / Neo4j graph queries (SQL audit log sufficient for temporal diff)
- Multi-tenant separation (one Postgres DB, one workspace)
- Automated LLM evaluation suite (manual review of extracted facts in v1)
- Human-review UI for `review_queue` (table exists, no UI in v1)
- Production observability (logs only, no Prometheus/Grafana in v1)