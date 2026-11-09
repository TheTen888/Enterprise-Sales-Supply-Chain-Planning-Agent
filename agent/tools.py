import json
from pathlib import Path

from pydantic import Field

from config.contracts import Contract, Quarter


class CapacityInput(Contract):
    factory_id: str
    target_quarter: Quarter
    required_units: int = Field(ge=1, le=1000000)


class Tools:
    def __init__(self, ingestion, rag, memory, source):
        self.ingestion = ingestion
        self.rag = rag
        self.memory = memory
        self.source = Path(source)

    def query_bom_and_ecn(self, scope, part_id):
        documents = [
            doc for doc in self.ingestion.current(scope) if doc["metadata"]["part_id"] == part_id
        ]
        bom = [doc for doc in documents if doc["metadata"]["kind"] == "bom"]
        ecn = [doc for doc in documents if doc["metadata"]["kind"] == "ecn"]
        if len(bom) != 1 or len(ecn) != 1:
            raise ValueError("Missing or conflicting active BOM/ECN; engineering review required")
        evidence = self.rag.retrieve(
            scope, f"{part_id} ECN-001 discount volume inspection lead time", part_id
        )
        required_docs = {doc["metadata"]["document_id"] for doc in documents}
        found = {row["metadata"]["document_id"] for row in evidence}
        if not required_docs.issubset(found):
            raise ValueError("Evidence budget omitted a required source")
        return {
            "unit_cost_cents": bom[0]["converted"]["unit_cost_cents"],
            "lead_days": ecn[0]["metadata"]["lead_days"],
            "evidence": evidence,
        }

    def check_factory_capacity(self, arguments):
        args = CapacityInput.model_validate(arguments)
        rows = json.loads((self.source / "factory_capacity.json").read_text())
        matches = [
            row
            for row in rows
            if row["factory_id"] == args.factory_id and row["quarter"] == args.target_quarter
        ]
        if len(matches) != 1:
            raise ValueError("Capacity unavailable; planner review required")
        row = matches[0]
        available = row["capacity_units"] - row["committed_units"]
        if not 0 <= row["committed_units"] <= row["capacity_units"]:
            raise ValueError("Invalid capacity facts")
        return {**row, "available_units": available, "can_fit": args.required_units <= available}

    def recall_customer_memory(self, scope):
        return self.memory.recall(scope)
