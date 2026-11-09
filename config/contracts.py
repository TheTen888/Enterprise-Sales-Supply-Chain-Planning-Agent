import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Quarter = Annotated[str, StringConstraints(pattern=r"^\d{4}-Q[1-4]$")]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Scope(Contract):
    customer_id: str
    project_id: str

    @property
    def key(self):
        return fingerprint(self.model_dump())


class Document(Contract):
    document_id: str
    customer_id: str
    project_id: str
    version: int = Field(ge=1)
    status: Literal["active", "deprecated", "deleted"] = "active"
    kind: Literal["ecn", "bom", "email"]
    path: str
    part_id: str
    lead_days: int | None = Field(default=None, ge=1)


class QuoteRequest(Contract):
    prompt: str
    part_id: str = "PART-001"
    quantity: int = Field(default=12000, ge=1, le=1000000)
    requested_days: int = Field(default=14, ge=1, le=365)
    quarter: Quarter = "2026-Q4"
    preferred_factory: str = "PLANT-A"
    unit_price_cents: int = Field(default=1500, ge=1)
    discount_bps: int = Field(default=500, ge=0, le=10000)


class Artifact(Contract):
    name: str
    revision: str
    status: Literal["needs_review", "blocked", "approved"]
    result: dict
    evidence: list[dict]


class Task(Contract):
    task_id: str
    parent_task_id: str | None = None
    agent: str
    state: Literal["working", "completed", "failed", "needs_review"]
    inputs: dict


class Message(Contract):
    sender: str
    recipient: str
    task_id: str
    content: dict
