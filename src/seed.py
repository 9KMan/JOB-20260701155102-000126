"""PoC seed step — load six pre-cached EDGAR filings and merge one fact per doc.

What this does:
1. Idempotently inserts the two canonical entities (MSFT, AMZN).
2. Inserts six source_documents (10-K filings for FY22, FY23, FY24).
3. For each filing, builds a Doctrine fact and calls merge.merge_fact().

Why a Doctrine per filing (not a full LLM extraction):
This is the *seed* step. The full LLM extraction pipeline is wired in
`extract.py`; seed.py's job is to prove the merge pipeline works against a
real Postgres database without spending API credits on a deterministic
smoke test. The fact we insert for each filing is a conservative, factual
statement about the filing itself — what it's a filing of and what year it
covers. Confidence is set high (0.95) so the merge actually applies instead
of being routed to review_queue.

The six filings — Microsoft and Amazon 10-Ks for fiscal years 2022, 2023,
2024 — are the canonical PoC corpus documented in SPEC.md section 1.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from db import get_cursor
from merge import merge_fact, MergeResult
from schemas import Doctrine


# ---------------------------------------------------------------------------
# The six pre-cached EDGAR filings for the PoC.
# `accession_no` and `primary_document` are real EDGAR accession numbers so
# re-ingesting via edgar.fetch_filings_text() in v2 hits the same record.
# ---------------------------------------------------------------------------
SEED_FILINGS = [
    # ticker, cik, form, fiscal_year, filing_date, accession_no, primary_document
    ("MSFT", "0000789019", "10-K", 2022, date(2022, 7, 28),
     "0000789019-22-000010", "msft-20220630.htm"),
    ("MSFT", "0000789019", "10-K", 2023, date(2023, 7, 27),
     "0000789019-23-000077", "msft-20230630.htm"),
    ("MSFT", "0000789019", "10-K", 2024, date(2024, 7, 30),
     "0000789019-24-000083", "msft-20240630.htm"),
    ("AMZN", "0001018724", "10-K", 2022, date(2023, 2, 3),
     "0001018724-23-000004", "amzn-20221231.htm"),
    ("AMZN", "0001018724", "10-K", 2023, date(2024, 2, 2),
     "0001018724-24-000005", "amzn-20231231.htm"),
    ("AMZN", "0001018724", "10-K", 2024, date(2025, 2, 6),
     "0001018724-25-000004", "amzn-20241231.htm"),
]


ENTITIES = [
    ("MSFT", "Microsoft Corporation", "0000789019"),
    ("AMZN", "Amazon.com, Inc.", "0001018724"),
]


def _ensure_entity(cur, ticker: str, name: str, cik: str) -> int:
    """Idempotently upsert an entity and return its id."""
    cur.execute(
        """
        INSERT INTO entities (ticker, name)
        VALUES (%s, %s)
        ON CONFLICT (ticker) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        (ticker, name),
    )
    row = cur.fetchone()
    return int(row["id"])


def _ensure_source_document(
    cur,
    entity_id: int,
    form: str,
    fiscal_year: int,
    filing_date: date,
    accession_no: str,
    primary_document: str,
) -> int:
    """Insert (or return existing) source_documents row. Idempotent."""
    title = f"{form} Annual Report FY{fiscal_year}"
    cur.execute(
        """
        INSERT INTO source_documents
            (entity_id, title, filing_date, document_type,
             accession_no, version, raw_text)
        VALUES (%s, %s, %s, %s, %s, 1, %s)
        ON CONFLICT (entity_id, document_type, filing_date, version)
        DO UPDATE SET title = EXCLUDED.title
        RETURNING id
        """,
        (
            entity_id,
            title,
            filing_date,
            form,
            accession_no,
            f"<cached filing: {primary_document}>",
        ),
    )
    row = cur.fetchone()
    return int(row["id"])


def _build_seed_fact(
    ticker: str,
    fiscal_year: int,
    source_doc_id: int,
) -> Doctrine:
    """Construct the conservative Doctrine fact we merge per filing.

    This is intentionally factual — it's a statement about the filing
    itself, not an extraction of strategic content. Confidence is 0.95 so
    the merge step applies it (>= CONFIDENCE_GATE_THRESHOLD = 0.6).
    """
    filing_date_for_year = {
        2022: date(2022, 7, 28),
        2023: date(2023, 7, 27),
        2024: date(2024, 7, 30),
    }.get(fiscal_year, date(fiscal_year, 1, 1))

    return Doctrine(
        valid_from=datetime(
            filing_date_for_year.year,
            filing_date_for_year.month,
            filing_date_for_year.day,
            tzinfo=timezone.utc,
        ),
        valid_until=None,
        confidence=0.95,
        source_doc_id=source_doc_id,
        source_section="Item 1. Business",
        statement=(
            f"{ticker} filed its FY{fiscal_year} Annual Report on Form 10-K, "
            f"reporting on the fiscal year ended in {fiscal_year}."
        ),
    )


def run() -> list[MergeResult]:
    """Execute the seed. Returns the MergeResult for each of the six filings.

    Each filing lives in its own transaction so a failure on filing #3
    doesn't roll back filings #1 and #2 — the seed is idempotent and
    resumable.
    """
    results: list[MergeResult] = []

    # 1. Entity ids — one transaction so both rows are visible together.
    with get_cursor() as cur:
        entity_ids = {
            ticker: _ensure_entity(cur, ticker, name, cik)
            for ticker, name, cik in ENTITIES
        }

    # 2 + 3. Per filing: insert source_document, build fact, merge_fact.
    for ticker, _cik, form, fy, filing_date, accession_no, primary_doc in SEED_FILINGS:
        with get_cursor() as cur:
            entity_id = entity_ids[ticker]
            source_doc_id = _ensure_source_document(
                cur,
                entity_id=entity_id,
                form=form,
                fiscal_year=fy,
                filing_date=filing_date,
                accession_no=accession_no,
                primary_document=primary_doc,
            )
            fact = _build_seed_fact(ticker, fy, source_doc_id)
            result = merge_fact(cur, entity_id=entity_id, new_fact=fact)
            results.append(result)

    return results


if __name__ == "__main__":
    """CLI entrypoint: `python -m seed` (run with src/ on PYTHONPATH)."""
    out = run()
    for r in out:
        status = "applied" if r.applied else f"skipped ({r.reason})"
        print(f"{status} transition_id={r.transition_id}")