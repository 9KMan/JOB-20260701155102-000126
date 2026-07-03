"""Document parsing — PDFs and HTML.

For SEC 10-K filings, detect section headers like "Item 1.", "Item 1A.",
"Item 7." (with optional period and trailing whitespace) and chunk by
them. Falls back to page-level sections when no header is detected.
"""
import re
from typing import Optional


# 10-K items commonly indexed by section. Matches "Item 1.", "Item 1A.",
# "Item 7.", "Item 8.", etc., with optional trailing period and whitespace.
_SECTION_HEADER_RE = re.compile(
    r"^\s*(Item\s+\d+[A-Z]?\.?)\s*[\.\s]*(.*?)\s*$",
    re.MULTILINE,
)


def parse_pdf(path: str) -> list[dict]:
    """Parse a PDF into (section_name, section_text) chunks.

    For SEC 10-K filings, sections map to Item 1, Item 1A, etc.
    Returns a list of {section: str, text: str} dicts.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pip install pdfplumber")

    # First pass: dump all text
    full_text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            full_text_parts.append(page.extract_text() or "")
    full_text = "\n".join(full_text_parts)

    # Detect sections via regex on the full text
    sections = _chunk_by_section_headers(full_text)
    if not sections:
        # Fallback: page-level
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                sections.append({"section": f"Page {i+1}", "text": text})
    return sections


def parse_html(html: str) -> list[dict]:
    """Parse HTML into (section_name, section_text) chunks.

    Detects section headers (h1/h2/h3 with "Item N." prefix); otherwise
    returns one chunk labelled "body".
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()

    # Try to detect sections via h1/h2/h3 with Item N. prefix
    sections = []
    current_section = None  # None means we haven't seen a section header yet
    current_text = []

    def flush():
        if current_section is None:
            # No section header seen — accumulated prose is "body"
            section_name = "body"
        else:
            section_name = current_section
        if current_text:
            sections.append({"section": section_name, "text": "\n".join(current_text)})

    for elem in soup.find_all(["h1", "h2", "h3", "p", "div"]):
        text = elem.get_text(strip=True)
        if not text:
            continue
        if elem.name in ("h1", "h2", "h3") and _is_section_header(text):
            flush()
            current_section = text
            current_text = []
        else:
            current_text.append(text)

    flush()

    if not sections:
        sections = [{"section": "body", "text": soup.get_text(separator="\n", strip=True)}]
    return sections


def _chunk_by_section_headers(text: str) -> list[dict]:
    """Split text on Item N. headers and return chunks."""
    matches = list(_SECTION_HEADER_RE.finditer(text))
    if not matches:
        return []

    chunks = []
    # Header text before first Item goes into a header section
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            chunks.append({"section": "header", "text": preamble})

    for i, m in enumerate(matches):
        section_name = m.group(1).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk_text = text[m.end():end].strip()
        chunks.append({"section": section_name, "text": chunk_text})

    return chunks


def _is_section_header(text: str) -> bool:
    """True if `text` looks like an SEC 10-K Item header."""
    return bool(_SECTION_HEADER_RE.match(text))