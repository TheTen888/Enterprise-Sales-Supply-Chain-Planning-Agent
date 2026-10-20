import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agents.workflow import FEEDBACK_REASONS, DraftWorkflow
from app.monitoring import session_metrics

ACTIONS = {
    "generate": {"action", "request_id"},
    "revise": {"action", "request_id", "job_id", "quantity"},
    "approve": {"action", "job_id", "option_id"},
    "reject": {"action", "request_id", "job_id", "reason_code", "note"},
    "explain": {"action", "job_id", "topic"},
}


class Showcase:
    def __init__(self, workflow: DraftWorkflow, workspace: Path, maximum_jobs=20):
        self.workflow, self.workspace = workflow, Path(workspace)
        self.actor = workflow.config["actor"]
        self.maximum_jobs = maximum_jobs
        self.lock = threading.RLock()
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-draft")
        self.pending = set()

    def close(self):
        self.worker.shutdown(wait=True)

    def monitor(self):
        with self.lock:
            return session_metrics(self.workflow, self.actor)

    def state(self):
        with self.lock:
            jobs = []
            for job_id in self.workflow.store.job_ids(self.actor):
                try:
                    job = self.workflow.read(self.actor, job_id)
                except ValueError:
                    row = self.workflow._job(self.actor, job_id)
                    if row["status"] != "invalidated":
                        raise
                    job = self.workflow.read(self.actor, job_id)
                job["trace"] = self.workflow.trace(self.actor, job_id)
                jobs.append(job)
            config = self.workflow.config
            facts = self.workflow.service.read_facts(
                config["customer_id"], config["project_id"], config["entity_id"]
            )
            return {
                "mode": "local_deterministic_showcase",
                "scope": {key: config[key] for key in ("customer_id", "project_id", "entity_id")},
                "facts": facts,
                "policy": config["policy"],
                "feedback_reasons": FEEDBACK_REASONS,
                "jobs": jobs,
                "job_limit": self.maximum_jobs,
                "customer_send_enabled": False,
                "llm_calls": 0,
                "external_api_calls": 0,
            }

    def _run(self, job_id):
        with self.lock:
            try:
                self.workflow.run(self.actor, job_id)
            except Exception:
                job = self.workflow.store.get(job_id)
                if job["status"] == "running":
                    self.workflow.store.transition(job_id, "failed")
                    self.workflow.store.event(job_id, "draft.failed", {"error_type": "WorkerError"})
            finally:
                self.pending.discard(job_id)

    def _schedule(self, job_id):
        if self.workflow.store.get(job_id)["status"] == "queued" and job_id not in self.pending:
            self.pending.add(job_id)
            self.worker.submit(self._run, job_id)

    def act(self, command):
        if not isinstance(command, dict):
            raise ValueError("JSON object required")
        action = command.get("action")
        if not isinstance(action, str) or action not in ACTIONS or set(command) != ACTIONS[action]:
            raise ValueError("unsupported action or fields")
        if "request_id" in command and (
            not isinstance(command["request_id"], str)
            or not re.fullmatch(r"[a-f0-9]{32}", command["request_id"])
        ):
            raise ValueError("request_id must be a 32-character lowercase hexadecimal value")
        if "job_id" in command and (
            not isinstance(command["job_id"], str)
            or not re.fullmatch(r"[a-f0-9]{32}", command["job_id"])
        ):
            raise ValueError("invalid draft identifier")
        with self.lock:
            if action in {"generate", "revise"}:
                if len(self.workflow.store.job_ids(self.actor)) >= self.maximum_jobs:
                    raise ValueError("local session draft limit reached; start a fresh session")
                if action == "generate":
                    config = self.workflow.config
                    job_id = self.workflow.submit(
                        self.actor,
                        config["customer_id"],
                        config["project_id"],
                        config["entity_id"],
                        key=command["request_id"],
                    )
                else:
                    job_id = self.workflow.revise_quantity(
                        self.actor,
                        command["job_id"],
                        command["quantity"],
                        key=command["request_id"],
                    )
                self._schedule(job_id)
                return {"job_id": job_id, "status": self.workflow.store.get(job_id)["status"]}
            job_id = command["job_id"]
            if action == "approve":
                self.workflow.approve(self.actor, job_id, command["option_id"])
            elif action == "reject":
                self.workflow.reject(
                    self.actor,
                    job_id,
                    command["reason_code"],
                    command["note"],
                    key=command["request_id"],
                )
            elif action == "explain":
                return self.workflow.explain(self.actor, job_id, command["topic"])
            return {"job_id": job_id, "status": self.workflow.store.get(job_id)["status"]}

    def export(self):
        result = self.state()
        result["scope_note"] = (
            "Live local demo session. Manager feedback awaits review; it is not a verified label. "
            "Recorded regression evidence is a separate snapshot. No customer dispatch."
        )
        return json.dumps(result, indent=2, allow_nan=False).encode()
