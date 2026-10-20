import hashlib
import json
from dataclasses import dataclass
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ValidationError(ValueError):
    pass


class InjectedFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class Change:
    offset: int
    payload: dict


@dataclass(frozen=True)
class Event:
    source: str
    event_id: str
    entity_id: str
    version: int
    operation: str
    customer_id: str
    project_id: str
    currency: str
    quantity: int
    unit_cost_cents: int
    unit_price_cents: int
    design_version: str
    content_hash: str


@dataclass(frozen=True)
class Record:
    event: Event
    extended_cost_cents: int
    extended_price_cents: int


class Fault:
    def __init__(self, phase: str | None = None):
        self.phase = phase
        self.fired = False

    def hit(self, phase: str):
        if self.phase == phase and not self.fired:
            self.fired = True
            raise InjectedFailure(phase)
