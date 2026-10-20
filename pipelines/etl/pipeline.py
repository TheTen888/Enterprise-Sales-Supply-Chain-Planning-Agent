import json
import time

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.extract import extract_changes
from pipelines.etl.load import load_candidate
from pipelines.etl.models import Fault, ValidationError
from pipelines.etl.policy import BatchPolicy
from pipelines.etl.transform import transform_event
from pipelines.etl.validate import validate_change, validate_record


class IncrementalETL:
    def __init__(
        self,
        source: Source,
        warehouse: Warehouse,
        batch_size: int = 1000,
        policy: BatchPolicy | None = None,
    ):
        self.source = source
        self.warehouse = warehouse
        self.batch_size = batch_size
        self.policy = policy
        self.previous_seconds = 0.0

    def process_batch(
        self, batch_id: str, fault: Fault | None = None, retry_quarantined: bool = False
    ) -> dict:
        started = time.perf_counter()
        fault = fault or Fault()
        batch = self.warehouse.batch(batch_id)
        if batch["source"] != self.source.name:
            raise ValueError("batch belongs to a different source")
        if batch["state"] == "completed":
            return self.report(batch_id, "completed", started, replay=True)
        if batch["state"] == "quarantined" and not retry_quarantined:
            return self.report(batch_id, "quarantined", started)
        if batch["state"] != "published":
            reasons, records = [], []
            try:
                changes = self.warehouse.raw(batch_id)
                keys = {
                    change.payload["entity_id"]
                    for change in changes
                    if isinstance(change.payload, dict)
                    and isinstance(change.payload.get("entity_id"), str)
                }
                scopes = self.warehouse.scopes_for(self.source.name, keys)
                for change in changes:
                    try:
                        key = (
                            change.payload.get("entity_id", "")
                            if isinstance(change.payload, dict)
                            else ""
                        )
                        scope = scopes.get(key) if isinstance(key, str) else None
                        event = validate_change(change.payload, self.source.name, scope)
                        record = transform_event(event)
                        validate_record(record)
                        records.append(record)
                    except ValidationError as exc:
                        reasons.append({"offset": change.offset, "reason": str(exc)})
                if reasons:
                    self.warehouse.quarantine(batch_id, reasons)
                    return self.report(batch_id, "quarantined", started)
                load_candidate(self.warehouse, batch_id, records)
                fault.hit("after_stage")
                self.warehouse.publish(batch_id, fault)
            except ValidationError as exc:
                self.warehouse.quarantine(batch_id, [{"reason": str(exc)}])
                return self.report(batch_id, "quarantined", started)
        fault.hit("after_publish")
        self.warehouse.commit_checkpoint(batch_id)
        return self.report(batch_id, "completed", started)

    def run_once(self, fault: Fault | None = None, retry_quarantined: bool = False) -> dict:
        batch = self.warehouse.pending(self.source.name)
        selected_size, mode = self.batch_size, "fixed"
        if batch is None:
            lower = self.warehouse.cursor(self.source.name)
            if self.policy:
                selected_size, mode = self.policy.select(
                    self.source.remaining(lower), self.previous_seconds
                )
            changes = extract_changes(self.source, lower, selected_size)
            if not changes:
                return {"status": "idle", "cursor": lower, "remaining_changes": 0}
            batch_id = self.warehouse.save_batch(self.source.name, lower, changes)
        else:
            batch_id = batch["batch_id"]
            selected_size = batch["upper_cursor"] - batch["lower_cursor"]
            mode = "pinned-recovery"
        report = self.process_batch(batch_id, fault, retry_quarantined)
        self.previous_seconds = report["elapsed_seconds"]
        report["batch_policy"] = {"mode": mode, "selected_size": selected_size}
        return report

    def drain(self) -> list[dict]:
        reports = []
        while True:
            report = self.run_once()
            if report["status"] == "idle":
                return reports
            reports.append(report)
            if report["status"] == "quarantined":
                return reports

    def report(self, batch_id: str, status: str, started: float, replay: bool = False) -> dict:
        batch = self.warehouse.batch(batch_id)
        elapsed = time.perf_counter() - started
        return {
            "status": status,
            "batch_id": batch_id,
            "source": batch["source"],
            "lower_cursor": batch["lower_cursor"],
            "upper_cursor": batch["upper_cursor"],
            "publication_id": batch["publication_id"],
            "cursor": self.warehouse.cursor(self.source.name),
            "remaining_changes": self.source.remaining(self.warehouse.cursor(self.source.name)),
            "replay": replay,
            "elapsed_seconds": round(elapsed, 6),
            "metrics": json.loads(batch["report"]),
        }
