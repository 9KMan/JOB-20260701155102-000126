"""LLM extractor — Pydantic-validated tool-calling on raw OpenAI/Anthropic SDKs.

Why raw SDKs (no LangChain):
- Determinism: Pydantic-validated tool-call is guaranteed by the schema
- Cost transparency: we see exactly how many tokens each extraction costs
- Debuggability: read the prompt and the model's tool-call args directly
- Production-proven: this pattern has shipped to prod (Job-119)

The LLM produces candidate updates only. The merge step (merge.py) is the
ONLY place that writes to persistent state.
"""
from typing import Optional
import json
from openai import OpenAI
from anthropic import Anthropic

from schemas import (
    Doctrine, Capability, ActiveState, ActiveObligation, Risk,
    ManagementDecision, CausalRelationship, EnterpriseTrajectory,
)


SCHEMA_REGISTRY = {
    "Doctrine": Doctrine,
    "Capability": Capability,
    "ActiveState": ActiveState,
    "ActiveObligation": ActiveObligation,
    "Risk": Risk,
    "ManagementDecision": ManagementDecision,
    "CausalRelationship": CausalRelationship,
    "EnterpriseTrajectory": EnterpriseTrajectory,
}


SYSTEM_PROMPT = """You are an enterprise intelligence analyst. Your job is to extract
structured facts about an enterprise from documents you read.

For each fact you extract, you must:
1. Call the appropriate tool with the structured data
2. Assign a confidence score (0.0-1.0) based on how explicit the fact is
   in the source text. Explicit numeric facts in a 10-K = 0.95. Implied
   strategic direction = 0.5-0.7.
3. Cite the section where you found the fact (e.g. "Item 1. Business")
4. Date the fact from when it became true (use the document's filing date
   as the valid_from unless the text clearly states an earlier date)

You may call multiple tools per document. Extract every fact that fits the schema."""


def extract_facts(
    document_text: str,
    document_title: str,
    filing_date: str,
    section_name: str,
    source_doc_id: int,
    openai_client: Optional[OpenAI] = None,
    anthropic_client: Optional[Anthropic] = None,
    model: str = "gpt-4o",
) -> list[dict]:
    """Extract facts from a single document section.

    Returns a list of dicts, each matching one of the 8 Pydantic schemas
    plus metadata (which schema, source_doc_id, source_section).
    The caller passes these to merge_fact().
    """
    if openai_client is None:
        openai_client = OpenAI()

    user_prompt = f"""Document: {document_title}
Filing date: {filing_date}
Section: {section_name}

{document_text}

Extract every enterprise fact that fits the schema. Use the tools provided."""

    # Define tools for each schema
    tools = [
        {"type": "function", "function": {
            "name": schema_name,
            "description": schema.__doc__ or schema_name,
            "parameters": schema.model_json_schema(),
        }}
        for schema_name, schema in SCHEMA_REGISTRY.items()
    ]

    response = openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tools=tools,
        tool_choice="auto",
    )

    candidates = []
    for tool_call in response.choices[0].message.tool_calls or []:
        schema_name = tool_call.function.name
        if schema_name not in SCHEMA_REGISTRY:
            continue
        schema_cls = SCHEMA_REGISTRY[schema_name]
        try:
            args = json.loads(tool_call.function.arguments)
            fact = schema_cls(
                source_doc_id=source_doc_id,
                source_section=section_name,
                **args,
            )
            candidates.append({
                "schema": schema_name,
                "fact": fact,
            })
        except Exception as e:
            # Log + skip malformed candidate; merge step never sees it
            print(f"Skipped malformed {schema_name}: {e}")
            continue

    return candidates
