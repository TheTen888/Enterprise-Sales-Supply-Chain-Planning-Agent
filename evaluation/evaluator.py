from config.contracts import QuoteRequest


def assess(case, result):
    route = case["expected_route"]
    checks = {"route": result.get("route") == route}
    if route == "direct":
        checks["no_tool_calls"] = len(result.get("events", [])) == 1
        return checks
    if route == "validation_error":
        return checks
    artifact = result.get("artifact", {})
    option = artifact.get("result", {})
    oracle = case["oracle"]
    request = QuoteRequest.model_validate(case["request"])
    available = oracle["factory_available"].get(option.get("factory_id"), 0)
    feasible_somewhere = any(
        request.quantity <= units for units in oracle["factory_available"].values()
    )
    evidence = artifact.get("evidence", [])
    texts = " ".join(row["text"] for row in evidence)
    checks.update(
        {
            "capacity": artifact.get("status") == "blocked"
            if not feasible_somewhere
            else artifact.get("status") == "needs_review" and request.quantity <= available,
            "timeline": option.get("lead_days", 0) >= oracle["minimum_days"],
            "calculation": option.get("unit_cost_cents") == oracle["unit_cost_cents"]
            and option.get("total_cost_cents") == oracle["unit_cost_cents"] * request.quantity
            and option.get("total_price_cents")
            == option.get("unit_price_cents", 0) * request.quantity
            and option.get("unit_price_cents", 0) * 9000 >= oracle["unit_cost_cents"] * 10000,
            "latest_ecn": any(
                row["metadata"]["document_id"] == "ECN-001" and row["metadata"]["version"] == 2
                for row in evidence
            )
            and all(row["metadata"]["status"] == "active" for row in evidence),
            "critical_conditions": "not signed or committed" in texts
            and "Inspection cannot be removed" in texts
            and "Future volume is not a signed commitment" in option.get("required_conditions", [])
            and "Required inspection remains included" in option.get("required_conditions", []),
            "scope": all(
                row["metadata"]["customer_id"] == "CUSTOMER-A"
                and row["metadata"]["project_id"] == "PROJECT-A"
                for row in evidence
            ),
            "tool_path": {"quote_agent", "capacity_agent", "risk_supervisor"}.issubset(
                {row["step"] for row in result.get("events", [])}
            ),
            "human_review": artifact.get("status") in {"needs_review", "blocked"},
        }
    )
    return checks


def unsafe_negative_control(case, result):
    from copy import deepcopy

    output = deepcopy(result)
    if case["expected_route"] == "quote":
        option = output["artifact"]["result"]
        option["factory_id"] = "PLANT-A"
        option["lead_days"] = case["request"].get("requested_days", 14)
        option["required_conditions"] = []
        output["artifact"]["status"] = "needs_review"
    return output
