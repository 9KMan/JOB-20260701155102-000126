"""SEC EDGAR ingest — pulls 10-K, 10-Q, 8-K filings.

SEC requires a real contact email in the User-Agent header.
"""
import httpx


def fetch_filings(
    cik: str,
    form_types: list[str],
    contact_email: str,
    base_url: str = "https://data.sec.gov",
) -> list[dict]:
    """Fetch recent filings for a CIK.

    Returns a list of {accession_no, form, filing_date, primary_document_url}.
    """
    headers = {
        "User-Agent": f"PersistentReasoningEngine {contact_email}",
        "Accept": "application/json",
    }
    client = httpx.Client(base_url=base_url, headers=headers, timeout=10.0)

    # SEC throttles to 10 req/sec — be polite
    resp = client.get(f"/submissions/CIK{cik.zfill(10)}.json")
    resp.raise_for_status()
    data = resp.json()

    filings = []
    recent = data.get("filings", {}).get("recent", {})
    for i, form in enumerate(recent.get("form", [])):
        if form not in form_types:
            continue
        filings.append({
            "accession_no": recent["accessionNumber"][i],
            "form": form,
            "filing_date": recent["filingDate"][i],
            "primary_document": recent["primaryDocument"][i],
            "primary_document_url": (
                f"/Archives/edgar/data/{int(cik)}/{recent['accessionNumber'][i].replace('-', '')}/"
                f"{recent['primaryDocument'][i]}"
            ),
        })
    return filings


def fetch_filing_text(
    cik: str,
    accession_no: str,
    primary_document: str,
    contact_email: str,
    base_url: str = "https://www.sec.gov",
) -> bytes:
    """Fetch the actual filing document (PDF or HTML)."""
    headers = {
        "User-Agent": f"PersistentReasoningEngine {contact_email}",
        "Accept": "*/*",
    }
    client = httpx.Client(base_url=base_url, headers=headers, timeout=30.0)
    url = f"/Archives/edgar/data/{int(cik)}/{accession_no.replace('-', '')}/{primary_document}"
    resp = client.get(url)
    resp.raise_for_status()
    return resp.content
