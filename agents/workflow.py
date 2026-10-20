import copy
from uuid import uuid4

from agents.roles import BusinessAgent, EngineeringAgent, validate_business, validate_engineering
from agents.tools import evidence_key, integer, requested_discount
from pipelines.etl.models import digest

QUERY = "customer price discount design material inspection engineering cost change"
FEEDBACK_REASONS = {
    "pricing_assumption": "Pricing assumption needs review",
    "capacity_schedule": "Capacity or schedule needs review",
    "missing_evidence": "Supporting evidence is incomplete",
    "commercial_context": "Customer context needs review",
}


class DraftWorkflow:
    def __init__(self, service, store, config, model, engineering=None, business=None):
        if config.get("synthetic") is not True or config.get("format_version") != 1:
            raise ValueError("synthetic version-one scenario required")
        integer(config["policy"]["minimum_margin_bps"], "minimum margin", 0, 9999)
        integer(config["policy"]["maximum_scenario_quantity"], "quantity ceiling", 1, 1000000)
        self.service, self.store, self.config, self.model = service, store, config, model
        self.engineering = engineering or EngineeringAgent()
        self.business = business or BusinessAgent()

    def submit(self, actor, customer, project, entity, quantity=None, key=None, parent_id=None):
        self.service.store.require_access(actor, customer, project)
        if (customer, project, entity) != tuple(
            self.config[name] for name in ("customer_id", "project_id", "entity_id")
        ):
            raise PermissionError("no trusted planning context for this scope")
        if quantity is not None:
            integer(
                quantity, "scenario quantity", 1, self.config["policy"]["maximum_scenario_quantity"]
            )
        key = uuid4().hex if key is None else key
        if not isinstance(key, str) or not key.strip() or len(key) > 100:
            raise ValueError("invalid idempotency key")
        if parent_id is not None:
            parent = self._job(actor, parent_id)
            if any(
                parent["request"][name] != value
                for name, value in (
                    ("customer_id", customer),
                    ("project_id", project),
                    ("entity_id", entity),
                )
            ):
                raise PermissionError("cannot revise another scope")
        request = {
            "customer_id": customer,
            "project_id": project,
            "entity_id": entity,
            "quantity": quantity,
            "as_of": self.config["as_of"],
            "scenario_kind": "manager_what_if" if quantity is not None else "published_order",
        }
        return self.store.enqueue(actor, request, digest({"actor": actor, "key": key}), parent_id)

    def _job(self, actor, job_id):
        job = self.store.get(job_id)
        if job["actor"] != actor:
            raise PermissionError("draft owner access denied")
        request = job["request"]
        self.service.store.require_access(actor, request["customer_id"], request["project_id"])
        return job

    def _capture(self, actor, request):
        pack = self.service.retrieve(
            actor,
            request["customer_id"],
            request["project_id"],
            request["entity_id"],
            QUERY,
            request["as_of"],
            2,
        )
        return pack, {
            "evidence": evidence_key(pack),
            "config": digest(self.config),
            "model": digest(self.model),
            "agent_runtime": digest(self.runtime_identity()),
        }

    def runtime_identity(self):
        return {
            role: getattr(agent, "identity", {"provider": "deterministic", "role": role})
            for role, agent in (("engineering", self.engineering), ("business", self.business))
        }

    def _record_model(self, job_id, role, result):
        analysis = result.get("model_analysis", {})
        for event in analysis.get("events", []):
            self.store.event(job_id, "model.call", {"role": role, **event})
        if analysis:
            self.store.event(
                job_id,
                "model.assessment",
                {"role": role, "decision": analysis["decision"], "tools": analysis["tools"]},
            )

    def _fresh(self, actor, job):
        _, current = self._capture(actor, job["request"])
        if current != job["payload"]["input_fingerprints"]:
            self.store.transition(job["job_id"], "invalidated")
            self.store.event(job["job_id"], "draft.inputs_changed", {})
            raise ValueError("draft inputs changed; generate a new draft")

    def run(self, actor, job_id):
        job = self._job(actor, job_id)
        if job["status"] in {"needs_review", "needs_capacity_review", "approved_internal"}:
            return self.read(actor, job_id)
        if not self.store.claim(job_id):
            raise ValueError("draft is not queued")
        try:
            pack, fingerprints = self._capture(actor, job["request"])
            facts = pack["facts"]
            quantity = (
                facts["quantity"]
                if job["request"]["quantity"] is None
                else job["request"]["quantity"]
            )
            integer(
                quantity, "scenario quantity", 1, self.config["policy"]["maximum_scenario_quantity"]
            )
            self.store.event(
                job_id,
                "evidence.retrieve",
                {
                    "fingerprint": fingerprints["evidence"],
                    "etl_publication": facts["publication_id"],
                    "cache_hit": pack["cache_hit"],
                    "chunks": [row["chunk_id"] for row in pack["citations"]],
                    "facts_backend": pack["facts_backend"],
                    "retrieval_backend": pack["retrieval_backend"],
                },
            )
            request = requested_discount(pack)
            engineering = self.engineering.run(
                copy.deepcopy(pack), quantity, copy.deepcopy(self.config), copy.deepcopy(self.model)
            )
            self._record_model(job_id, "engineering", engineering)
            validate_engineering(pack, quantity, self.config, self.model, engineering)
            self.store.event(
                job_id,
                "engineering.complete",
                {
                    "tools": [
                        "published_cost_totals",
                        "source_condition_checks",
                        "local_risk_model.score",
                    ],
                    "costing": engineering["costing"],
                    "risk": engineering["risk"],
                    "handoff_conditions": [row["id"] for row in engineering["constraints"]],
                },
            )
            business = self.business.run(
                copy.deepcopy(facts),
                quantity,
                copy.deepcopy(request),
                copy.deepcopy(engineering),
                copy.deepcopy(self.config["policy"]),
            )
            self._record_model(job_id, "business", business)
            validate_business(
                facts, quantity, request, engineering, self.config["policy"], business
            )
            self.store.event(
                job_id,
                "business.complete",
                {
                    "tool": "integer_cent_pricing",
                    "options": business["options"],
                },
            )
            payload = {
                "mode": "mock_guarded_two_role_workflow"
                if "model_analysis" in engineering
                and engineering["model_analysis"]["identity"].get("simulated")
                else "model_guarded_two_role_workflow"
                if "model_analysis" in engineering
                else "deterministic_two_role_workflow",
                "runtime_identity": self.runtime_identity(),
                "job_id": job_id,
                "revision": job["revision"],
                "scope": {name: facts[name] for name in ("customer_id", "project_id", "entity_id")},
                "input_fingerprints": fingerprints,
                "facts": facts,
                "quantity": quantity,
                "scenario_kind": job["request"]["scenario_kind"],
                "customer_volume_committed": job["request"]["scenario_kind"] == "published_order",
                "engineering": engineering,
                "business": business,
                "recalculated": [
                    "total_cost",
                    "quote_totals",
                    "capacity_load",
                    "schedule_slack",
                    "allocation_utilization",
                    "risk_score",
                ],
                "reused": [
                    "published_unit_cost",
                    "frozen_model_parameters",
                    "source_document_versions_when_unchanged",
                ],
                "external_api_calls": sum(
                    not event.get("simulated", False) and event.get("provider") == "aws_bedrock"
                    for row in (engineering, business)
                    for event in row.get("model_analysis", {}).get("events", [])
                ),
                "llm_calls": sum(
                    not event.get("simulated", False)
                    for row in (engineering, business)
                    for event in row.get("model_analysis", {}).get("events", [])
                ),
                "mock_model_calls": sum(
                    event.get("simulated", False)
                    for row in (engineering, business)
                    for event in row.get("model_analysis", {}).get("events", [])
                ),
                "customer_send_enabled": False,
            }
            _, current = self._capture(actor, job["request"])
            if current != fingerprints:
                raise ValueError("inputs changed during draft generation")
            self.store.publish(job_id, payload)
            self.store.event(job_id, "draft.validated", {"payload_hash": digest(payload)})
        except Exception as exc:
            for event in getattr(exc, "events", []):
                self.store.event(job_id, "model.call", event)
            self.store.transition(job_id, "failed")
            self.store.event(job_id, "draft.failed", {"error_type": type(exc).__name__})
            raise
        return self.read(actor, job_id)

    def read(self, actor, job_id):
        job = self._job(actor, job_id)
        if job["status"] in {"needs_review", "needs_capacity_review", "approved_internal"}:
            self._fresh(actor, job)
        return {
            "job_id": job_id,
            "status": job["status"],
            "revision": job["revision"],
            "parent_id": job["parent_id"],
            "draft": job["payload"],
            "approval": job["approval"],
            "approval_valid": job["status"] == "approved_internal",
            "feedback": self.store.feedback(job_id),
        }

    def revise_quantity(self, actor, job_id, quantity, key=None):
        job = self._job(actor, job_id)
        request = job["request"]
        return self.submit(
            actor,
            request["customer_id"],
            request["project_id"],
            request["entity_id"],
            quantity=quantity,
            key=key,
            parent_id=job_id,
        )

    def approve(self, actor, job_id, option_id):
        job = self._job(actor, job_id)
        if job["status"] == "approved_internal":
            self._fresh(actor, job)
            if job["approval"]["option_id"] != option_id:
                raise ValueError("another option already approved; create a new revision")
            return self.read(actor, job_id)
        if job["status"] != "needs_review":
            raise ValueError("draft is not eligible for approval")
        self._fresh(actor, job)
        option = next(
            (row for row in job["payload"]["business"]["options"] if row["option_id"] == option_id),
            None,
        )
        if option is None or not option["margin_allowed"]:
            raise ValueError("option violates pricing policy")
        approval = {
            "actor": actor,
            "option_id": option_id,
            "revision": job["revision"],
            "payload_hash": job["payload_hash"],
            "input_fingerprints": job["payload"]["input_fingerprints"],
            "scope": "internal review only; not customer dispatch",
        }
        self.store.approve(job_id, approval)
        return self.read(actor, job_id)

    def reject(self, actor, job_id, reason_code, note, key=None):
        job = self._job(actor, job_id)
        if not isinstance(reason_code, str) or reason_code not in FEEDBACK_REASONS:
            raise ValueError("select a supported feedback reason")
        if not isinstance(note, str) or not 5 <= len(note.strip()) <= 500:
            raise ValueError("feedback note must contain 5 to 500 characters")
        key = uuid4().hex if key is None else key
        if not isinstance(key, str) or not key.strip() or len(key) > 100:
            raise ValueError("invalid feedback idempotency key")
        if job["status"] in {"needs_review", "needs_capacity_review"}:
            self._fresh(actor, job)
        self.store.reject(job, reason_code, note.strip(), digest({"actor": actor, "key": key}))
        return self.read(actor, job_id)

    def explain(self, actor, job_id, topic):
        job = self.read(actor, job_id)
        if job["status"] not in {"needs_review", "needs_capacity_review", "approved_internal"}:
            raise ValueError("current draft required for follow-up")
        draft = job["draft"]
        options = {row["option_id"]: row for row in draft["business"]["options"]}
        answers = {
            "discount_limit": {
                "requested": options["customer_request"],
                "counteroffer": options["counteroffer"],
                "minimum_margin_bps": self.config["policy"]["minimum_margin_bps"],
                "reason": "Current published cost sets the margin floor; unsigned volume does not authorize cost savings",
            },
            "volume_change": {
                "published_quantity": draft["facts"]["quantity"],
                "scenario_quantity": draft["quantity"],
                "scenario_kind": draft["scenario_kind"],
                "recalculated": draft["recalculated"],
                "reason": "A manager what-if is not a customer commitment; ETL facts remain unchanged",
            },
            "delivery_risk": draft["engineering"]["risk"],
        }
        if topic not in answers:
            raise ValueError("supported topics: discount_limit, volume_change, delivery_risk")
        self.store.event(job_id, "manager.follow_up", {"topic": topic})
        return {
            "topic": topic,
            "answer": answers[topic],
            "citations": draft["engineering"]["constraints"],
        }

    def trace(self, actor, job_id):
        self._job(actor, job_id)
        return self.store.trace(job_id)
