from agents.tools import cost_totals, integer, pricing_options, reviewed_conditions, risk_analysis


class EngineeringAgent:
    def run(self, pack, quantity, config, model):
        return {
            "role": "engineering",
            "costing": cost_totals(pack["facts"], quantity),
            "constraints": reviewed_conditions(pack, config),
            "risk": risk_analysis(pack["facts"], quantity, config, model),
            "recommendation": "Preserve material and inspection; seek separate engineering review for design simplification",
        }


class BusinessAgent:
    def run(self, facts, quantity, request, engineering, policy):
        return {
            "role": "business",
            "discount_request": request,
            "options": pricing_options(
                facts,
                quantity,
                engineering["costing"]["unit_cost_cents"],
                request["discount_bps"],
                policy,
            ),
            "recommended_option_id": "counteroffer",
            "conditions": [row["id"] for row in engineering["constraints"]],
            "requires_capacity_review": engineering["risk"]["requires_capacity_review"],
            "next_action": "Planner must resolve capacity before approval"
            if engineering["risk"]["requires_capacity_review"]
            else "Manager reviews pricing options; no automatic customer send",
        }


def validate_engineering(pack, quantity, config, model, result):
    for name in ("unit_cost_cents", "total_cost_cents"):
        integer(result["costing"][name], name)
    if (
        result["role"] != "engineering"
        or result["costing"]["unit_cost_cents"] != pack["facts"]["unit_cost_cents"]
        or result["costing"]["total_cost_cents"] != quantity * pack["facts"]["unit_cost_cents"]
        or result["constraints"] != reviewed_conditions(pack, config)
        or result["risk"] != risk_analysis(pack["facts"], quantity, config, model)
    ):
        raise ValueError("engineering handoff failed source and arithmetic checks")


def validate_business(facts, quantity, request, engineering, policy, result):
    if (
        result["role"] != "business"
        or result["discount_request"] != request
        or result["conditions"] != [row["id"] for row in engineering["constraints"]]
        or result["requires_capacity_review"] != engineering["risk"]["requires_capacity_review"]
        or result["recommended_option_id"] != "counteroffer"
    ):
        raise ValueError("business handoff failed condition checks")
    options = result["options"]
    if [row["option_id"] for row in options] != [
        "retain_price",
        "customer_request",
        "counteroffer",
    ]:
        raise ValueError("unexpected quote options")
    cost, current = facts["unit_cost_cents"], facts["unit_price_cents"]
    requested = (current * (10000 - request["discount_bps"]) + 5000) // 10000
    denominator = 10000 - policy["minimum_margin_bps"]
    minimum = -(-(cost * 10000) // denominator)
    for option, price in zip(options, [current, requested, max(requested, minimum)], strict=True):
        for name in ("quantity", "unit_price_cents", "revenue_cents", "total_cost_cents"):
            integer(option[name], name, 1, 10**24)
        if (
            type(option["gross_profit_cents"]) is not int
            or type(option["margin_bps"]) is not int
            or type(option["margin_allowed"]) is not bool
        ):
            raise ValueError("invalid quote numeric types")
        profit, revenue = quantity * (price - cost), quantity * price
        if (
            option["quantity"] != quantity
            or option["unit_price_cents"] != price
            or option["revenue_cents"] != revenue
            or option["total_cost_cents"] != cost * quantity
            or option["gross_profit_cents"] != profit
            or option["margin_bps"] != profit * 10000 // revenue
            or option["margin_allowed"]
            != ((price - cost) * 10000 >= policy["minimum_margin_bps"] * price)
        ):
            raise ValueError("quote failed independent arithmetic checks")
