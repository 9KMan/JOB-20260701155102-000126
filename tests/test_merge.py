"""Real tests of merge_fact invariants using mock cursor.

These verify the SQL merge_fact issues (REQ-05..REQ-10) without needing
a live Postgres. Integration tests against a real Postgres are in
test_merge_integration.py and are skipped if DATABASE_URL is unreachable.

Cursor call sequence (per merge.merge_fact):
  1. cursor.execute("SELECT pg_advisory_xact_lock(%s)", ...) — no fetchone
  2. cursor.execute("SELECT ... FROM enterprise_state WHERE ... valid_until IS NULL ...")
     cursor.fetchone() -> current  (None or row dict)
  3. cursor.execute("SELECT 1 FROM enterprise_state_transitions WHERE ...")
     cursor.fetchone() -> existing (None or row)
     if existing -> return already-extracted (no further calls)
  4. if confidence < 0.6:
       cursor.execute("INSERT INTO review_queue ...")  -- no fetchone
       return low_confidence
  5. if current and _contradicts:
       cursor.execute("UPDATE enterprise_state SET valid_until = ...") -- no fetchone
  6. cursor.execute("INSERT INTO enterprise_state ... RETURNING id")
     cursor.fetchone() -> new_id  (dict like {"id": 42})
  7. cursor.execute("INSERT INTO enterprise_state_transitions ... RETURNING id")
     cursor.fetchone() -> transition_id  (dict like {"id": 100})
  8. return MergeResult(applied=True, transition_id=transition_id)
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from merge import CONFIDENCE_GATE_THRESHOLD, _contradicts, MergeResult
from schemas import Doctrine


def _make_fact(confidence=0.85, source_doc_id=1, source_section="Item 1. Business"):
    return Doctrine(
        valid_from=datetime(2024, 1, 15, tzinfo=timezone.utc),
        confidence=confidence,
        source_doc_id=source_doc_id,
        source_section=source_section,
        statement="We are a cloud-first company.",
    )


def test_confidence_gate_threshold_value():
    """REQ-08: confidence < 0.6 lands in review_queue."""
    assert CONFIDENCE_GATE_THRESHOLD == 0.6


def test_contradicts_returns_true_conservatively():
    """v1 conservatively supersedes any fact in same category."""
    current = {"id": 1, "fact_json": {"statement": "old"}}
    new = _make_fact()
    assert _contradicts(new, current) is True


def test_contradicts_signature_accepts_dict_only():
    """merge._contradicts is typed for the with-state case; merge_fact guards the None case."""
    new = _make_fact()
    assert _contradicts(new, {"id": 1, "fact_json": {}}) is True


def test_merge_fact_advisory_lock_sql():
    """REQ-06: pg_advisory_xact_lock(entity_id) is the first SQL issued."""
    cur = MagicMock()
    # Execute #1 (advisory lock) — no fetchone
    # Execute #2 (current state) — fetchone -> None
    # Execute #3 (idempotency) — fetchone -> None (not yet extracted)
    # Execute #6 (INSERT new state RETURNING id) — fetchone -> {"id": 42}
    # Execute #7 (INSERT transition RETURNING id) — fetchone -> {"id": 100}
    cur.fetchone.side_effect = [None, None, {"id": 42}, {"id": 100}]

    from merge import merge_fact
    fact = _make_fact()
    merge_fact(cur, entity_id=1, new_fact=fact)

    # First call MUST be the advisory lock
    first_call = cur.execute.call_args_list[0]
    assert "pg_advisory_xact_lock" in first_call[0][0]
    assert first_call[0][1] == (1,)


def test_merge_fact_idempotency_skips_second_apply():
    """REQ-07: same (source_doc_id, source_section, entity_id) returns already-extracted."""
    cur = MagicMock()
    # Execute #2 (current state) -> None
    # Execute #3 (idempotency) -> {"id": 99} (already extracted)
    cur.fetchone.side_effect = [None, {"id": 99}]

    from merge import merge_fact
    fact = _make_fact()
    result = merge_fact(cur, entity_id=1, new_fact=fact)

    assert result.applied is False
    assert result.reason == "already-extracted"
    # Should NOT have called INSERT into enterprise_state
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO enterprise_state" in c[0][0]
    ]
    assert len(insert_calls) == 0


def test_merge_fact_low_confidence_to_review_queue():
    """REQ-08: confidence < 0.6 → review_queue, NOT enterprise_state."""
    cur = MagicMock()
    # Execute #2 -> None (no current state)
    # Execute #3 -> None (not yet extracted)
    cur.fetchone.side_effect = [None, None]

    from merge import merge_fact
    fact = _make_fact(confidence=0.3)
    result = merge_fact(cur, entity_id=1, new_fact=fact)

    assert result.applied is False
    assert result.reason == "low_confidence"
    # review_queue INSERT should have been called
    review_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO review_queue" in c[0][0]
    ]
    assert len(review_calls) == 1
    # enterprise_state INSERT should NOT have been called
    state_inserts = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO enterprise_state" in c[0][0]
    ]
    assert len(state_inserts) == 0


def test_merge_fact_conflict_marks_old_valid_until():
    """REQ-09: when new fact supersedes current, old fact's valid_until is set."""
    cur = MagicMock()
    # Execute #2 -> existing current state
    # Execute #3 -> None (not yet extracted)
    # Execute #6 -> new_id
    # Execute #7 -> transition_id
    cur.fetchone.side_effect = [
        {"id": 5, "fact_json": {"statement": "old"}},
        None,
        {"id": 42},
        {"id": 100},
    ]

    from merge import merge_fact
    new_fact = _make_fact()
    result = merge_fact(cur, entity_id=1, new_fact=new_fact)

    assert result.applied is True
    # Should have called UPDATE enterprise_state SET valid_until = ...
    update_calls = [
        c for c in cur.execute.call_args_list
        if "UPDATE enterprise_state" in c[0][0] and "valid_until" in c[0][0]
    ]
    assert len(update_calls) == 1
    # The valid_until should equal new_fact.valid_from
    update_args = update_calls[0][0][1]
    assert update_args[0] == new_fact.valid_from
    assert update_args[1] == 5


def test_merge_fact_records_transition():
    """REQ-10: every applied fact produces a transition row."""
    cur = MagicMock()
    cur.fetchone.side_effect = [
        None,                                  # current state: none
        None,                                  # idempotency: not extracted
        {"id": 42},                            # INSERT new state RETURNING
        {"id": 100},                           # INSERT transition RETURNING
    ]

    from merge import merge_fact
    fact = _make_fact()
    result = merge_fact(cur, entity_id=1, new_fact=fact)

    assert result.applied is True
    assert result.transition_id == 100
    transition_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO enterprise_state_transitions" in c[0][0]
    ]
    assert len(transition_calls) == 1


def test_merge_fact_is_only_writer_to_enterprise_state():
    """REQ-05: architectural invariant — only merge.py WRITES to enterprise_state.

    Reads (SELECT) are allowed anywhere. Writes (INSERT/UPDATE/DELETE) must
    appear exclusively in src/merge.py.
    """
    import subprocess
    write_pattern = r"(INSERT INTO|UPDATE|DELETE FROM)\s+enterprise_state"
    result = subprocess.run(
        ["grep", "-rlnE", write_pattern,
         "src/", "--include=*.py"],
        capture_output=True, text=True,
        cwd="/home/deploy/squad/build-worker/JOB-20260701155102-000126",
    )
    files = sorted(set(line.strip() for line in result.stdout.strip().split("\n") if line.strip()))
    assert files == ["src/merge.py"], (
        f"REQ-05 violation: enterprise_state WRITES found in {files}"
    )