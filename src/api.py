"""FastAPI query layer — read-only endpoints over enterprise_state.

Uses src.db.get_cursor as a context manager. The DB connection helper lives
in db.py so tests can patch it via api.get_db.
"""
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from db import get_cursor

app = FastAPI(title="Persistent Reasoning Engine API")

# Serve static UI (src/static/index.html) at /ui
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")


# FastAPI dependency — alias for get_cursor so tests can patch `api.get_db`.
def get_db():
    """FastAPI dependency: yields a cursor (delegates to get_cursor)."""
    with get_cursor() as cur:
        yield cur


@app.get("/entities/{ticker}/state")
def current_state(ticker: str):
    """Return currently-valid facts for an entity (valid_until IS NULL).

    Unlike /state-as-of which takes a timestamp, this returns the live
    state vector — exactly what the partial UNIQUE index guarantees at
    most one of per (entity_id, category).
    """
    with get_cursor() as cur:
        cur.execute("SELECT id FROM entities WHERE ticker = %s", (ticker,))
        entity = cur.fetchone()
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity {ticker} not found")

        cur.execute(
            """
            SELECT category, fact_json, valid_from, confidence,
                   source_doc_id, source_section
            FROM enterprise_state
            WHERE entity_id = %s
              AND valid_until IS NULL
            ORDER BY category, valid_from DESC
            """,
            (entity["id"],),
        )
        return {
            "ticker": ticker,
            "state": [dict(r) for r in cur.fetchall()],
        }


@app.get("/entities/{ticker}/state-as-of")
def state_as_of(
    ticker: str,
    timestamp: datetime = Query(...),
):
    """Return the enterprise state vector as it was at the given timestamp."""
    with get_cursor() as cur:
        cur.execute("SELECT id FROM entities WHERE ticker = %s", (ticker,))
        entity = cur.fetchone()
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity {ticker} not found")

        cur.execute(
            """
            SELECT category, fact_json, valid_from, valid_until,
                   confidence, source_doc_id, source_section
            FROM enterprise_state
            WHERE entity_id = %s
              AND valid_from <= %s
              AND (valid_until IS NULL OR valid_until > %s)
            ORDER BY category, valid_from DESC
            """,
            (entity["id"], timestamp, timestamp),
        )
        return {
            "ticker": ticker,
            "as_of": timestamp.isoformat(),
            "state": [dict(r) for r in cur.fetchall()],
        }


@app.get("/entities/{ticker}/changes")
def changes(
    ticker: str,
    from_ts: datetime = Query(..., alias="from"),
    to_ts: datetime = Query(..., alias="to"),
):
    """Return the state changes for an entity between two timestamps."""
    with get_cursor() as cur:
        cur.execute("SELECT id FROM entities WHERE ticker = %s", (ticker,))
        entity = cur.fetchone()
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity {ticker} not found")

        cur.execute(
            """
            SELECT t.transition_at, t.category,
                   prev.fact_json AS prev_state,
                   new.fact_json AS new_state,
                   t.source_doc_id
            FROM enterprise_state_transitions t
            LEFT JOIN enterprise_state prev ON prev.id = t.prev_state_id
            LEFT JOIN enterprise_state new  ON new.id = t.new_state_id
            WHERE t.entity_id = %s
              AND t.transition_at BETWEEN %s AND %s
            ORDER BY t.transition_at
            """,
            (entity["id"], from_ts, to_ts),
        )
        return {
            "ticker": ticker,
            "from": from_ts.isoformat(),
            "to": to_ts.isoformat(),
            "changes": [dict(r) for r in cur.fetchall()],
        }


@app.get("/entities/{ticker}/risks-active")
def risks_active(ticker: str):
    """Return currently-active risks for an entity."""
    with get_cursor() as cur:
        cur.execute("SELECT id FROM entities WHERE ticker = %s", (ticker,))
        entity = cur.fetchone()
        if not entity:
            raise HTTPException(status_code=404, detail=f"Entity {ticker} not found")

        cur.execute(
            """
            SELECT fact_json, valid_from, confidence, source_doc_id, source_section
            FROM enterprise_state
            WHERE entity_id = %s
              AND category = 'risk'
              AND valid_until IS NULL
            ORDER BY confidence DESC
            """,
            (entity["id"],),
        )
        return {
            "ticker": ticker,
            "risks_active": [dict(r) for r in cur.fetchall()],
        }


@app.get("/health")
def health():
    return {"status": "ok"}