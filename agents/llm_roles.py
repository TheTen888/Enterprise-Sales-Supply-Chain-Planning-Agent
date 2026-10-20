from agents.assessment import AssessmentError, ModelAssessor
from agents.roles import BusinessAgent, EngineeringAgent
from agents.tools import risk_analysis


def documents_from_pack(pack):
    facts = pack["facts"]
    return [
        {
            "citation_id": row["chunk_id"],
            "document_id": row["document_id"],
            "version": row["version"],
            "kind": row["kind"],
            "text": row["text"],
            "customer_id": facts["customer_id"],
            "project_id": facts["project_id"],
            "design_version": facts["design_version"],
            "active": True,
            "approved": True,
        }
        for row in pack["citations"]
    ]


def build_task(role, facts, quantity, documents, policy, gap=0):
    return {
        "role": role,
        "request": "Prepare internal pricing options for the customer's discount request. Preserve engineering requirements and check capacity.",
        "authorized": True,
        "customer_id": facts["customer_id"],
        "project_id": facts["project_id"],
        "facts": facts,
        "quantity": quantity,
        "discount_bps": 500,
        "policy": policy,
        "other_committed_units": gap,
        "usable_capacity_units": quantity,
        "documents": documents,
    }


def require_supported_assessment(result, expected, action):
    actual = {
        row["condition_id"]: row["citation_id"] for row in result["decision"]["condition_evidence"]
    }
    support = {row["id"]: row["chunk_id"] for row in expected}
    if (
        result["decision"]["status"] != "ready"
        or actual != support
        or result["decision"]["next_action"] != action
    ):
        raise AssessmentError(
            "model decision did not satisfy source and action checks", result["events"]
        )


class ModelEngineeringAgent(EngineeringAgent):
    def __init__(self, client):
        self.assessor = ModelAssessor(client)
        self.identity = {**self.assessor.identity, "role": "engineering"}

    def run(self, pack, quantity, config, model):
        task = build_task(
            "engineering", pack["facts"], quantity, documents_from_pack(pack), config["policy"]
        )
        result = self.assessor.assess(
            task,
            {"calculate_capacity": lambda: risk_analysis(pack["facts"], quantity, config, model)},
        )
        expected = super().run(pack, quantity, config, model)
        require_supported_assessment(
            result,
            expected["constraints"],
            "capacity_review"
            if expected["risk"]["requires_capacity_review"]
            else "preserve_requirements",
        )
        expected["model_analysis"] = {**result, "identity": self.identity}
        expected["source_documents"] = task["documents"]
        return expected


class ModelBusinessAgent(BusinessAgent):
    def __init__(self, client):
        self.assessor = ModelAssessor(client)
        self.identity = {**self.assessor.identity, "role": "business"}

    def run(self, facts, quantity, request, engineering, policy):
        task = build_task(
            "business",
            facts,
            quantity,
            engineering["source_documents"],
            policy,
            engineering["risk"]["capacity_shortfall_units"],
        )
        task["discount_bps"] = request["discount_bps"]
        result = self.assessor.assess(task)
        require_supported_assessment(
            result,
            engineering["constraints"],
            "capacity_review"
            if engineering["risk"]["requires_capacity_review"]
            else "price_options",
        )
        expected = super().run(facts, quantity, request, engineering, policy)
        expected["model_analysis"] = {**result, "identity": self.identity}
        return expected
