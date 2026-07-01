"""Merge step — the ONLY place that writes to enterprise_state.

Architectural invariant: every persistent state change goes through merge_fact().
The LLM extractor produces *candidates* but never commits.

Five protections:
1. Advisory locks per entity — serializes concurrent merges
2. Idempotency — same (source_doc_id, source_section, entity_id) only writes once
3. Confidence gate — facts below 0.6 go to review_queue
4. Conflict detection — new facts that contradict current state mark the old valid_until
5. Transition logging — every state change recorded in enterprise_state_transitions
"""
from dataclasses import dataclass
from typing import Optional
import psycopg2
import psycopg2.extras

from schemas import FactBase


CONFIDENCE_GATE_THRESHOLD = 0.6


@dataclass
class MergeResult:
    applied: bool
    reason: Optional[str] = None
    transition_id: Optional[int] = None


def merge_fact(
    cursor,
    entity_id: int,
    new_fact: FactBase,
) -> MergeResult:
    """Apply a new fact to the enterprise state. Idempotent.

    Args:
        cursor: an open psycopg2 cursor inside a transaction
        entity_id: the entity this fact is about (e.g. Microsoft's row id)
        new_fact: the candidate fact to apply

    Returns:
        MergeResult(applied=True/False, reason=str, transition_id=int|None)
    """
    # 1. Advisory lock keyed on entity_id — serializes concurrent merges
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (entity_id,))

    # 2. Look up the current state of this fact's category
    cursor.execute(
        """
        SELECT id, fact_json, valid_from
        FROM enterprise_state
        WHERE entity_id = %s
          AND category = %s
          AND valid_until IS NULL
        ORDER BY valid_from DESC
        LIMIT 1
        """,
        (entity_id, new_fact.__class__.__name__.lower()),
    )
    current = cursor.fetchone()

    # 3. Idempotency check: did we already extract this fact from this doc?
    cursor.execute(
        """
        SELECT 1 FROM enterprise_state_transitions
        WHERE source_doc_id = %s
          AND source_section = %s
          AND entity_id = %s
        """,
        (new_fact.source_doc_id, new_fact.source_section, entity_id),
    )
    if cursor.fetchone():
        return MergeResult(applied=False, reason="already-extracted")

    # 4. Confidence gate
    if new_fact.confidence < CONFIDENCE_GATE_THRESHOLD:
        cursor.execute(
            """
            INSERT INTO review_queue (entity_id, fact_json, reason, created_at)
            VALUES (%s, %s, 'low_confidence', NOW())
            """,
            (entity_id, new_fact.model_dump_json()),
        )
        return MergeResult(applied=False, reason="low_confidence")

    # 5. Conflict detection: does the new fact contradict the current state?
    if current and _contradicts(new_fact, current):
        cursor.execute(
            """
            UPDATE enterprise_state
            SET valid_until = %s
            WHERE id = %s
            """,
            (new_fact.valid_from, current["id"]),
        )

    # 6. Insert the new fact as the currently-valid state
    cursor.execute(
        """
        INSERT INTO enterprise_state
          (entity_id, category, fact_json, valid_from, valid_until,
           confidence, source_doc_id, source_section)
        VALUES (%s, %s, %s, %s, NULL, %s, %s, %s)
        RETURNING id
        """,
        (
            entity_id,
            new_fact.__class__.__name__.lower(),
            new_fact.model_dump_json(),
            new_fact.valid_from,
            new_fact.confidence,
            new_fact.source_doc_id,
            new_fact.source_section,
        ),
    )
    new_id = cursor.fetchone()["id"]

    # 7. Record the transition (for the temporal-diff query)
    cursor.execute(
        """
        INSERT INTO enterprise_state_transitions
          (entity_id, category, prev_state_id, new_state_id,
           source_doc_id, transition_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        RETURNING id
        """,
        (
            entity_id,
            new_fact.__class__.__name__.lower(),
            current["id"] if current else None,
            new_id,
            new_fact.source_doc_id,
        ),
    )
    transition_id = cursor.fetchone()["id"]

    return MergeResult(applied=True, transition_id=transition_id)


def _contradicts(new_fact: FactBase, current: dict) -> bool:
    """Determine if a new fact contradicts the currently-valid state.

    This is a heuristic: if both facts are about the same numeric/quantitative
    claim and they differ, treat as a contradiction. The superseding fact's
    valid_from becomes the old fact's valid_until.

    For this reference implementation, we conservatively treat any new fact
    on the same category as a contradiction — the merge step marks the old
    fact as no longer valid (valid_until = new_fact.valid_from). Real
    production logic would use field-specific rules.
    """
    return True  # Conservative: every new fact supersedes the current one
