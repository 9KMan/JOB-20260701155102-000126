"""Document parsing — PDFs and HTML."""
from typing import Optional


def parse_pdf(path: str) -> list[dict]:
    """Parse a PDF into (section_name, section_text) chunks.

    Returns a list of {section: str, text: str} dicts.
    For SEC 10-K filings, sections map to Item 1, Item 1A, etc.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pip install pdfplumber")

    sections = []
    with pdfplumber.open(path) as pdf:
        # Naive: one section per page for now; production would detect headers
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            sections.append({
                "section": f"Page {i+1}",
                "text": text,
            })
    return sections


def parse_html(html: str) -> list[dict]:
    """Parse HTML into (section_name, section_text) chunks."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return [{"section": "body", "text": text}]
