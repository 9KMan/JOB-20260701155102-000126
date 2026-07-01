"""Enterprise object schemas — the 8 categories from the JD.

Each schema has:
- valid_from + valid_until (temporal validity)
- confidence (LLM-assigned, gates below 0.6)
- source_doc_id + source_section (provenance)

These are the candidate outputs of the LLM extraction pipeline. The merge step
(merge.py) applies them as updates to the persistent state.
"""
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


class FactBase(BaseModel):
    """Common fields for every enterprise fact."""
    valid_from: datetime
    valid_until: Optional[datetime] = None
    confidence: float = Field(ge=0, le=1)
    source_doc_id: int
    source_section: str  # e.g. "Item 1. Business" or "Risk Factors"


class Doctrine(FactBase):
    """A long-held belief or principle the enterprise operates by."""
    statement: str


class Capability(FactBase):
    """Something the enterprise can demonstrably do — products, services, scale."""
    name: str
    description: str
    category: Literal["product", "service", "operational", "technical"]
    scale_metric: Optional[str] = None


class ActiveState(FactBase):
    """A current condition the enterprise is in."""
    state: str


class ActiveObligation(FactBase):
    """A commitment the enterprise has made (debt, lease, contract, regulatory)."""
    description: str
    amount: Optional[float] = None
    currency: Optional[str] = None
    due_date: Optional[datetime] = None
    counterparty: Optional[str] = None


class Risk(FactBase):
    """A risk the enterprise has disclosed."""
    description: str
    category: Literal[
        "operational", "financial", "regulatory", "competitive",
        "cybersecurity", "supply_chain", "other",
    ]
    severity: Literal["low", "medium", "high", "critical"]


class ManagementDecision(FactBase):
    """A decision the management has made or announced."""
    decision: str
    rationale: Optional[str] = None
    announced_at: datetime


class CausalRelationship(FactBase):
    """A causal link between two enterprise facts."""
    cause: str  # reference to another fact
    effect: str


class EnterpriseTrajectory(FactBase):
    """A summary of where the enterprise is heading."""
    direction: Literal[
        "growing", "stable", "declining", "transforming", "uncertain",
    ]
    description: str
    evidence_facts: list[str] = Field(default_factory=list)
