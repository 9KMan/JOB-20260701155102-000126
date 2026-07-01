"""pytest fixtures."""
import os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def fact_dict():
    return {
        "valid_from": "2024-01-15T00:00:00Z",
        "valid_until": None,
        "confidence": 0.85,
        "source_doc_id": 1,
        "source_section": "Item 1. Business",
        "statement": "We are a cloud-first company.",
    }
