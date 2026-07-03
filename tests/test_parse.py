"""Tests for document parsers — HTML section detection (PDF tested lightly)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from parse import parse_html, _chunk_by_section_headers, _is_section_header


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def test_html_section_detection_msft_fixture():
    """MSFT fixture has Item 1. Business and Productivity subsections."""
    path = os.path.join(FIXTURES, "msft_2024_10k_item1.html")
    with open(path) as f:
        html = f.read()
    sections = parse_html(html)
    # At least 1 chunk (header + sections)
    assert len(sections) >= 1
    # Body text should include "cloud-first"
    all_text = "\n".join(s["text"] for s in sections)
    assert "cloud-first" in all_text


def test_html_section_detection_amzn_fixture():
    """AMZN fixture has Item 1A. Risk Factors — verify the parser captures it."""
    path = os.path.join(FIXTURES, "amzn_2023_10k_item1a.html")
    with open(path) as f:
        html = f.read()
    sections = parse_html(html)
    assert len(sections) >= 1
    all_text = "\n".join(s["text"] for s in sections)
    # Fixture content covers competition, regulation, supply chain
    assert "competition" in all_text.lower() or "competitive" in all_text.lower()
    assert "supply chain" in all_text.lower() or "third-party" in all_text.lower()
    # The h1 contains "Item 1A." — verify it appears in section names
    section_names = [s["section"] for s in sections]
    assert any("Item 1A" in n for n in section_names)


def test_section_header_regex_basic():
    """Item 1., Item 1A., Item 7., Item 8. are recognized."""
    assert _is_section_header("Item 1. Business")
    assert _is_section_header("Item 1A. Risk Factors")
    assert _is_section_header("Item 7. Management's Discussion")
    assert _is_section_header("Item 8. Financial Statements")


def test_section_header_regex_false_positives_rejected():
    """Non-headers are rejected."""
    assert not _is_section_header("We are a cloud-first company.")
    assert not _is_section_header("Microsoft Corporation")
    assert not _is_section_header("Item not a number")


def test_chunk_by_section_headers_basic():
    """Plain text with Item 1. / Item 1A. headers is chunked correctly."""
    text = """\
HEADER PREAMBLE

Item 1. Business
We sell cloud services.

Item 1A. Risk Factors
Cyber attacks.

Item 7. MD&A
Revenue grew 20%.
"""
    chunks = _chunk_by_section_headers(text)
    section_names = [c["section"] for c in chunks]
    assert "Item 1." in section_names or any("Item 1." in n for n in section_names)
    assert any("Item 1A." in n for n in section_names)
    assert any("Item 7." in n for n in section_names)
    # Preamble captured
    assert chunks[0]["section"] == "header"
    assert "preamble" in chunks[0]["text"].lower() or "HEADER" in chunks[0]["text"]


def test_chunk_by_section_headers_no_headers():
    """Text without Item N. headers returns empty list."""
    chunks = _chunk_by_section_headers("Just some plain text without any section markers.")
    assert chunks == []


def test_html_no_headers_falls_back_to_body():
    """Plain HTML with no h1/h2/h3 Item headers returns one body chunk."""
    html = "<html><body><p>Just some prose.</p></body></html>"
    sections = parse_html(html)
    assert len(sections) == 1
    assert sections[0]["section"] == "body"
    assert "Just some prose" in sections[0]["text"]