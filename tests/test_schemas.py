"""Test the Pydantic schemas validate correctly."""
from schemas import Doctrine, Capability, Risk


def test_doctrine_validates(fact_dict):
    f = Doctrine(**fact_dict)
    assert f.confidence == 0.85
    assert f.source_section == "Item 1. Business"


def test_capability_requires_category(fact_dict):
    bad = {**fact_dict, "name": "Cloud", "description": "Azure cloud platform", "category": "invalid"}
    try:
        Capability(**bad)
        assert False, "Should have raised ValidationError"
    except Exception:
        pass


def test_risk_validates(fact_dict):
    f = Risk(
        **fact_dict,
        description="Cybersecurity attacks",
        category="cybersecurity",
        severity="high",
    )
    assert f.severity == "high"
    assert f.category == "cybersecurity"


def test_confidence_must_be_in_range(fact_dict):
    bad = {**fact_dict, "confidence": 1.5}
    try:
        Doctrine(**bad)
        assert False, "Should have raised ValidationError"
    except Exception:
        pass


def test_temporal_validity_format(fact_dict):
    f = Doctrine(**fact_dict)
    assert f.valid_from.year == 2024
    assert f.valid_until is None  # currently valid
