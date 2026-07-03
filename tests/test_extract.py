"""Tests for the LLM extractor — uses mock OpenAI/Anthropic clients.

These verify:
- Pydantic-validated tool-calling args are accepted
- Malformed candidates are skipped (merge step never sees them)
- All 8 schemas can be invoked via tool name
"""
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from extract import extract_facts, SCHEMA_REGISTRY


def _mock_openai_response(tool_calls_data: list[dict]):
    """Build a mock OpenAI ChatCompletion response with the given tool calls."""
    tool_calls = []
    for tc in tool_calls_data:
        tool_call = MagicMock()
        tool_call.function.name = tc["name"]
        tool_call.function.arguments = tc["arguments"]
        tool_calls.append(tool_call)

    choice = MagicMock()
    choice.message.tool_calls = tool_calls

    response = MagicMock()
    response.choices = [choice]
    return response


def test_schema_registry_has_all_eight():
    """SCHEMA_REGISTRY exposes all 8 Pydantic schemas."""
    expected = {
        "Doctrine", "Capability", "ActiveState", "ActiveObligation",
        "Risk", "ManagementDecision", "CausalRelationship", "EnterpriseTrajectory",
    }
    assert set(SCHEMA_REGISTRY.keys()) == expected


def test_extract_facts_validates_with_pydantic():
    """A well-formed tool call is wrapped as a Pydantic instance."""
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_response([
        {
            "name": "Doctrine",
            "arguments": '{"valid_from": "2024-01-15T00:00:00Z", '
                          '"confidence": 0.95, '
                          '"source_doc_id": 1, '
                          '"source_section": "Item 1. Business", '
                          '"statement": "cloud-first"}',
        }
    ])
    candidates = extract_facts(
        document_text="We are a cloud-first company.",
        document_title="MSFT 10-K",
        filing_date="2024-01-15",
        section_name="Item 1. Business",
        source_doc_id=1,
        openai_client=client,
    )
    assert len(candidates) == 1
    assert candidates[0]["schema"] == "Doctrine"
    assert candidates[0]["fact"].confidence == 0.95


def test_extract_facts_skips_malformed_candidates():
    """Malformed tool-call args (bad enum, missing field) are skipped."""
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_response([
        # Bad severity — not in Literal
        {
            "name": "Risk",
            "arguments": '{"valid_from": "2024-01-15T00:00:00Z", '
                          '"confidence": 0.9, '
                          '"source_doc_id": 1, '
                          '"source_section": "Item 1A", '
                          '"description": "X", '
                          '"category": "cybersecurity", '
                          '"severity": "catastrophic"}',
        },
        # Good one
        {
            "name": "Doctrine",
            "arguments": '{"valid_from": "2024-01-15T00:00:00Z", '
                          '"confidence": 0.9, '
                          '"source_doc_id": 1, '
                          '"source_section": "Item 1. Business", '
                          '"statement": "ok"}',
        },
    ])
    candidates = extract_facts(
        document_text="...",
        document_title="Test",
        filing_date="2024-01-15",
        section_name="Item 1A",
        source_doc_id=1,
        openai_client=client,
    )
    assert len(candidates) == 1
    assert candidates[0]["schema"] == "Doctrine"


def test_extract_facts_skips_unknown_tool_name():
    """Unknown tool names are silently skipped."""
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_response([
        {"name": "NotASchema", "arguments": "{}"},
    ])
    candidates = extract_facts(
        document_text="...",
        document_title="Test",
        filing_date="2024-01-15",
        section_name="X",
        source_doc_id=1,
        openai_client=client,
    )
    assert candidates == []


def test_extract_facts_uses_correct_tool_definitions():
    """The OpenAI call passes one tool definition per schema."""
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_response([])
    extract_facts(
        document_text="...",
        document_title="Test",
        filing_date="2024-01-15",
        section_name="X",
        source_doc_id=1,
        openai_client=client,
    )
    call = client.chat.completions.create.call_args
    tools = call.kwargs["tools"]
    assert len(tools) == 8
    tool_names = {t["function"]["name"] for t in tools}
    assert tool_names == set(SCHEMA_REGISTRY.keys())


def test_extract_facts_passes_confidence_in_system_prompt():
    """System prompt instructs the model to assign confidence 0-1."""
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_openai_response([])
    extract_facts(
        document_text="...",
        document_title="Test",
        filing_date="2024-01-15",
        section_name="X",
        source_doc_id=1,
        openai_client=client,
    )
    call = client.chat.completions.create.call_args
    messages = call.kwargs["messages"]
    system_msg = next(m for m in messages if m["role"] == "system")
    assert "confidence" in system_msg["content"].lower()