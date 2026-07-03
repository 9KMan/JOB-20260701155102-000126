"""SEC EDGAR ingest — pulls 10-K, 10-Q, 8-K filings.

SEC requires a real contact email in the User-Agent header.
Provides sync (fetch_filings) and async (fetch_filings_async) variants.
The async variant uses httpx.AsyncClient + asyncio.Semaphore(8) to stay
under SEC's 10 req/sec rate limit.
"""
import asyncio
from typing import Optional

import httpx


DEFAULT_BASE_URL = "https://data.sec.gov"
FILINGS_BASE_URL = "https://www.sec.gov"
RATE_LIMIT_SEMAPHORE = 8  # stay safely under SEC's 10 req/sec


def fetch_filings(
    cik: str,
    form_types: list[str],
    contact_email: str,
    base_url: str = DEFAULT_BASE_URL,
) -> list[dict]:
    """Fetch recent filings for a CIK (sync).

    Returns a list of {accession_no, form, filing_date, primary_document_url}.
    """
    headers = _headers(contact_email)
    with httpx.Client(base_url=base_url, headers=headers, timeout=10.0) as client:
        resp = client.get(f"/submissions/CIK{cik.zfill(10)}.json")
        resp.raise_for_status()
        data = resp.json()

    filings = []
    recent = data.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form not in form_types:
            continue
        accession_no = recent["accessionNumber"][i]
        primary_document = recent["primaryDocument"][i]
        filings.append({
            "accession_no": accession_no,
            "form": form,
            "filing_date": recent["filingDate"][i],
            "primary_document": primary_document,
            "primary_document_url": (
                f"/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}/"
                f"{primary_document}"
            ),
        })
    return filings


async def fetch_filings_async(
    cik: str,
    form_types: list[str],
    contact_email: str,
    base_url: str = DEFAULT_BASE_URL,
    semaphore_value: int = RATE_LIMIT_SEMAPHORE,
) -> list[dict]:
    """Fetch recent filings for a CIK (async, rate-limited).

    Uses asyncio.Semaphore(semaphore_value) to cap concurrent requests.
    Suitable for batched fetches across many CIKs.
    """
    sem = asyncio.Semaphore(semaphore_value)
    headers = _headers(contact_email)

    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=10.0
    ) as client:
        async with sem:
            resp = await client.get(f"/submissions/CIK{cik.zfill(10)}.json")
            resp.raise_for_status()
            data = resp.json()

    filings = []
    recent = data.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form not in form_types:
            continue
        accession_no = recent["accessionNumber"][i]
        primary_document = recent["primaryDocument"][i]
        filings.append({
            "accession_no": accession_no,
            "form": form,
            "filing_date": recent["filingDate"][i],
            "primary_document": primary_document,
            "primary_document_url": (
                f"/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}/"
                f"{primary_document}"
            ),
        })
    return filings


async def fetch_multiple_ciks(
    ciks: list[str],
    form_types: list[str],
    contact_email: str,
    base_url: str = DEFAULT_BASE_URL,
    semaphore_value: int = RATE_LIMIT_SEMAPHORE,
) -> dict[str, list[dict]]:
    """Fetch filings for multiple CIKs concurrently with rate limiting."""
    tasks = [
        fetch_filings_async(
            cik=cik,
            form_types=form_types,
            contact_email=contact_email,
            base_url=base_url,
            semaphore_value=semaphore_value,
        )
        for cik in ciks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out = {}
    for cik, res in zip(ciks, results):
        if isinstance(res, Exception):
            out[cik] = []
        else:
            out[cik] = res
    return out


def fetch_filing_text(
    cik: str,
    accession_no: str,
    primary_document: str,
    contact_email: str,
    base_url: str = FILINGS_BASE_URL,
) -> bytes:
    """Fetch the actual filing document (PDF or HTML)."""
    headers = _headers(contact_email, accept_all=True)
    with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
        url = f"/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}/{primary_document}"
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def _headers(contact_email: str, accept_all: bool = False) -> dict:
    """Build the EDGAR-required headers."""
    return {
        "User-Agent": f"PersistentReasoningEngine {contact_email}",
        "Accept": "*/*" if accept_all else "application/json",
    }