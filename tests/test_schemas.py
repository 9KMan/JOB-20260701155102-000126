"""Test the Pydantic schemas validate correctly — all 8 schemas."""
import pytest
from pydantic import ValidationError

from schemas import (
    Doctrine, Capability, ActiveState, ActiveObligation, Risk,
    ManagementDecision, CausalRelationship, EnterpriseTrajectory,
)


def _base(**overrides):
    """Return a minimal valid Doctrine payload, with optional overrides."""
    base = {
        "valid_from": "2024-01-15T00:00:00Z",
        "valid_until": None,
        "confidence": 0.85,
        "source_doc_id": 1,
        "source_section": "Item 1. Business",
        "statement": "We are a cloud-first company.",
    }
    base.update(overrides)
    return base


def test_doctrine_validates(fact_dict):
    f = Doctrine(**fact_dict)
    assert f.confidence == 0.85
    assert f.source_section == "Item 1. Business"


def test_capability_requires_category(fact_dict):
    bad = {**fact_dict, "name": "Cloud", "description": "Azure cloud platform", "category": "invalid"}
    with pytest.raises(ValidationError):
        Capability(**bad)


def test_capability_accepts_valid_categories(fact_dict):
    for cat in ("product", "service", "operational", "technical"):
        c = Capability(**{**fact_dict, "name": "X", "description": "Y", "category": cat})
        assert c.category == cat


def test_risk_validates(fact_dict):
    f = Risk(
        **fact_dict,
        description="Cybersecurity attacks",
        category="cybersecurity",
        severity="high",
    )
    assert f.severity == "high"
    assert f.category == "cybersecurity"


def test_risk_rejects_bad_severity(fact_dict):
    bad = {
        **fact_dict,
        "description": "X",
        "category": "cybersecurity",
        "severity": "catastrophic",  # not in Literal
    }
    with pytest.raises(ValidationError):
        Risk(**bad)


def test_active_state_validates(fact_dict):
    s = ActiveState(**{**fact_dict, "state": "Scaling cloud capacity"})
    assert "Scaling" in s.state


def test_active_obligation_validates(fact_dict):
    o = ActiveObligation(
        **{**fact_dict, "description": "Operating lease", "amount": 5000000.0,
           "currency": "USD", "counterparty": "Some Landlord LLC"}
    )
    assert o.amount == 5000000.0
    assert o.currency == "USD"


def test_management_decision_validates(fact_dict):
    d = ManagementDecision(
        **{**fact_dict, "decision": "Acquire Nuance",
           "rationale": "Healthcare AI strategy", "announced_at": "2024-01-15T00:00:00Z"}
    )
    assert d.decision == "Acquire Nuance"


def test_causal_relationship_validates(fact_dict):
    c = CausalRelationship(**{**fact_dict, "cause": "Cyber attack", "effect": "Service outage"})
    assert c.cause == "Cyber attack"
    assert c.effect == "Service outage"


def test_enterprise_trajectory_validates(fact_dict):
    t = EnterpriseTrajectory(
        **{**fact_dict, "direction": "transforming",
           "description": "Pivoting to AI-first", "evidence_facts": ["fact-1", "fact-2"]}
    )
    assert t.direction == "transforming"
    assert len(t.evidence_facts) == 2


def test_enterprise_trajectory_rejects_bad_direction(fact_dict):
    bad = {**fact_dict, "direction": "spiraling-up", "description": "x", "evidence_facts": []}
    with pytest.raises(ValidationError):
        EnterpriseTrajectory(**bad)


def test_confidence_must_be_in_range(fact_dict):
    bad = {**fact_dict, "confidence": 1.5}
    with pytest.raises(ValidationError):
        Doctrine(**bad)


def test_confidence_negative_rejected(fact_dict):
    bad = {**fact_dict, "confidence": -0.1}
    with pytest.raises(ValidationError):
        Doctrine(**bad)


def test_temporal_validity_format(fact_dict):
    f = Doctrine(**fact_dict)
    assert f.valid_from.year == 2024
    assert f.valid_until is None  # currently valid


def test_all_eight_schemas_exist():
    """REQ-01: exactly 8 enterprise-object Pydantic schemas."""
    from schemas import FactBase
    expected = {Doctrine, Capability, ActiveState, ActiveObligation,
                Risk, ManagementDecision, CausalRelationship, EnterpriseTrajectory}
    for cls in expected:
        assert issubclass(cls, FactBase), f"{cls.__name__} must inherit from FactBase"

    # All require valid_from, confidence, source_doc_id, source_section
    for cls in expected:
        fields = set(cls.model_fields.keys())
        assert {"valid_from", "confidence", "source_doc_id", "source_section"}.issubset(fields), \
            f"{cls.__name__} missing FactBase fields"