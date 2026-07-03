"""FastAPI endpoint tests — TestClient + mocked cursor.

These do NOT require a live Postgres; we patch api.get_cursor to return
a controllable context manager yielding a MagicMock cursor.
"""
import sys
import os
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _make_client_with_cursor(cur):
    """Patch api.get_cursor and return (client, patcher). Caller stops patcher."""
    from api import app

    class _Ctx:
        def __enter__(self_inner):
            return cur
        def __exit__(self_inner, *args):
            return False

    patcher = patch("api.get_cursor", return_value=_Ctx())
    patcher.start()
    return TestClient(app), patcher


def test_health():
    """REQ: GET /health returns {status: ok}."""
    cur = MagicMock()
    client, patcher = _make_client_with_cursor(cur)
    try:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
    finally:
        patcher.stop()


def test_state_unknown_entity_returns_404():
    """Unknown ticker -> 404."""
    cur = MagicMock()
    cur.fetchone.return_value = None  # entity not found
    client, patcher = _make_client_with_cursor(cur)
    try:
        resp = client.get("/entities/UNKNOWN/state")
        assert resp.status_code == 404
    finally:
        patcher.stop()


def test_state_returns_current_facts():
    """REQ-12: GET /entities/{ticker}/state returns currently-valid facts."""
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 1}
    cur.fetchall.return_value = [
        {
            "category": "doctrine",
            "fact_json": {"statement": "cloud-first"},
            "valid_from": datetime(2024, 1, 15, tzinfo=timezone.utc),
            "confidence": 0.95,
            "source_doc_id": 1,
            "source_section": "Item 1. Business",
        },
        {
            "category": "capability",
            "fact_json": {"name": "Azure", "description": "cloud platform"},
            "valid_from": datetime(2024, 1, 15, tzinfo=timezone.utc),
            "confidence": 0.9,
            "source_doc_id": 1,
            "source_section": "Item 1. Business",
        },
    ]
    client, patcher = _make_client_with_cursor(cur)
    try:
        resp = client.get("/entities/MSFT/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "MSFT"
        assert len(data["state"]) == 2
        assert data["state"][0]["category"] == "doctrine"
    finally:
        patcher.stop()


def test_state_as_of_bitemporal_query():
    """REQ-13: state-as-of returns facts valid at the historical timestamp."""
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 1}
    cur.fetchall.return_value = [
        {"category": "doctrine", "fact_json": {},
         "valid_from": datetime(2023, 1, 1, tzinfo=timezone.utc),
         "valid_until": None, "confidence": 0.9,
         "source_doc_id": 1, "source_section": "Item 1"},
    ]
    client, patcher = _make_client_with_cursor(cur)
    try:
        resp = client.get("/entities/MSFT/state-as-of?timestamp=2023-06-01T00:00:00Z")
        assert resp.status_code == 200
        data = resp.json()
        assert "as_of" in data
        assert data["as_of"].startswith("2023-06-01T00:00:00")
        assert len(data["state"]) == 1
    finally:
        patcher.stop()


def test_changes_returns_temporal_diff():
    """REQ-14: /changes returns transition log between timestamps."""
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 1}
    cur.fetchall.return_value = [
        {
            "transition_at": datetime(2024, 6, 15, tzinfo=timezone.utc),
            "category": "risk",
            "prev_state": {"description": "old risk"},
            "new_state": {"description": "new risk"},
            "source_doc_id": 2,
        }
    ]
    client, patcher = _make_client_with_cursor(cur)
    try:
        resp = client.get("/entities/MSFT/changes?from=2024-01-01T00:00:00Z&to=2024-12-31T00:00:00Z")
        assert resp.status_code == 200
        data = resp.json()
        assert "from" in data and "to" in data
        assert len(data["changes"]) == 1
        assert data["changes"][0]["category"] == "risk"
    finally:
        patcher.stop()


def test_risks_active_filters_severity():
    """REQ: /risks-active returns currently-valid risks ordered by confidence."""
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 1}
    cur.fetchall.return_value = [
        {"fact_json": {"description": "X", "severity": "high"},
         "valid_from": datetime(2024, 1, 1, tzinfo=timezone.utc),
         "confidence": 0.95, "source_doc_id": 1, "source_section": "Item 1A"},
    ]
    client, patcher = _make_client_with_cursor(cur)
    try:
        resp = client.get("/entities/MSFT/risks-active")
        assert resp.status_code == 200
        data = resp.json()
        assert "risks_active" in data
        assert len(data["risks_active"]) == 1
    finally:
        patcher.stop()


def test_state_endpoint_in_routes():
    """REQ-12: /state endpoint exists in the app routes."""
    from api import app
    paths = [getattr(r, "path", str(r)) for r in app.routes]
    assert "/entities/{ticker}/state" in paths