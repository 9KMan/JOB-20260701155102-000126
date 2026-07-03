"""Tests for EDGAR ingest — User-Agent header injection, async semaphore."""
import asyncio
import os
import sys
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import edgar
from edgar import fetch_filings, fetch_filings_async, fetch_multiple_ciks, _headers


def test_headers_include_contact_email():
    """REQ: User-Agent header must include EDGAR_CONTACT_EMAIL."""
    headers = _headers("test@example.com")
    assert "test@example.com" in headers["User-Agent"]
    assert "PersistentReasoningEngine" in headers["User-Agent"]


def test_headers_accept_json_default():
    """Default Accept is application/json."""
    headers = _headers("test@example.com")
    assert headers["Accept"] == "application/json"


def test_headers_accept_all_when_requested():
    """accept_all=True for filing-text fetches uses Accept: */*."""
    headers = _headers("test@example.com", accept_all=True)
    assert headers["Accept"] == "*/*"


def test_fetch_filings_sync_parses_response(monkeypatch):
    """fetch_filings extracts filings from EDGAR JSON response."""
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "filings": {
            "recent": {
                "form": ["10-K", "10-Q", "8-K"],
                "accessionNumber": ["0001564590-22-000015", "0001564590-21-000099", "0001193125-22-123456"],
                "filingDate": ["2022-07-28", "2021-10-26", "2022-03-15"],
                "primaryDocument": ["msft-20220630.htm", "msft-20210930.htm", "msft-20220315.htm"],
            }
        }
    }
    fake_response.raise_for_status = MagicMock()

    with patch.object(edgar.httpx, "Client") as MockClient:
        client_instance = MagicMock()
        client_instance.get.return_value = fake_response
        client_instance.__enter__ = MagicMock(return_value=client_instance)
        client_instance.__exit__ = MagicMock(return_value=False)
        MockClient.return_value = client_instance

        filings = fetch_filings(
            cik="789019",
            form_types=["10-K", "10-Q"],
            contact_email="dev@example.com",
        )

    assert len(filings) == 2  # 10-K + 10-Q (8-K filtered out)
    assert filings[0]["form"] == "10-K"
    assert filings[0]["accession_no"] == "0001564590-22-000015"
    assert "/Archives/edgar/data/789019/" in filings[0]["primary_document_url"]


def test_fetch_filings_async_uses_semaphore(monkeypatch):
    """fetch_filings_async uses asyncio.Semaphore for rate limiting."""
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0001564590-22-000015"],
                "filingDate": ["2022-07-28"],
                "primaryDocument": ["msft-20220630.htm"],
            }
        }
    }
    fake_response.raise_for_status = MagicMock()

    with patch.object(edgar.httpx, "AsyncClient") as MockClient:
        client_instance = MagicMock()
        client_instance.get = AsyncMock(return_value=fake_response)
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = client_instance

        result = asyncio.run(fetch_filings_async(
            cik="789019",
            form_types=["10-K"],
            contact_email="dev@example.com",
        ))
    assert len(result) == 1


def test_fetch_multiple_ciks_returns_dict():
    """fetch_multiple_ciks returns {cik: filings} for each CIK."""
    fake_response = MagicMock()
    fake_response.json.return_value = {
        "filings": {
            "recent": {
                "form": ["10-K"],
                "accessionNumber": ["0001564590-22-000015"],
                "filingDate": ["2022-07-28"],
                "primaryDocument": ["x.htm"],
            }
        }
    }
    fake_response.raise_for_status = MagicMock()

    with patch.object(edgar.httpx, "AsyncClient") as MockClient:
        client_instance = MagicMock()
        client_instance.get = AsyncMock(return_value=fake_response)
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = client_instance

        result = asyncio.run(fetch_multiple_ciks(
            ciks=["789019", "1018724"],
            form_types=["10-K"],
            contact_email="dev@example.com",
        ))
    assert "789019" in result
    assert "1018724" in result
    assert len(result["789019"]) == 1