"""Test the merge step invariants."""
from datetime import datetime, timezone
from schemas import Doctrine
from merge import MergeResult, CONFIDENCE_GATE_THRESHOLD


def test_merge_result_dataclass():
    r = MergeResult(applied=True, transition_id=42)
    assert r.applied is True
    assert r.transition_id == 42
    assert r.reason is None


def test_low_confidence_threshold():
    """Verify the confidence gate is at the documented threshold."""
    assert CONFIDENCE_GATE_THRESHOLD == 0.6
