import re
from decimal import Decimal

from pipelines.etl.models import digest
from risk_model.dataset import canonical_day, visible
from risk_model.training import score


def integer(value, name, lower=0, upper=10**12):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"invalid {name}")
    return value


def ceil_div(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def evidence_key(pack):
    return digest(
        {
            key: pack[key]
            for key in ("as_of", "facts", "citations", "revisions", "status", "context")
        }
    )


def reviewed_conditions(pack, config):
    if pack["status"] != "ready" or not pack["context"]["complete"]:
        raise ValueError("complete current evidence required")
    citations = {row["chunk_id"]: row for row in pack["citations"]}
    result = []
    for required in config["reviewed_conditions"]:
        row = citations.get(required["chunk_id"])
        if (
            row is None
            or row["document_id"] != required["document_id"]
            or required["text"].casefold() not in row["text"].casefold()
        ):
            raise ValueError("reviewed condition missing or changed: " + required["id"])
        result.append(
            {
                "id": required["id"],
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "version": row["version"],
                "source_hash": row["source_hash"],
                "text": required["text"],
            }
        )
    return result


def requested_discount(pack):
    values = []
    for row in pack["citations"]:
        if row["kind"] == "customer_request":
            for value in re.findall(
                r"(?<![\w.])(\d+(?:\.\d{1,2})?)\s+percent\s+(?:price\s+)?discount\b",
                row["text"],
                re.I,
            ):
                values.append((int(Decimal(value) * 100), row["chunk_id"]))
    if len(values) != 1 or not 0 < values[0][0] < 10000:
        raise ValueError("one unambiguous customer discount request required")
    return {"discount_bps": values[0][0], "chunk_id": values[0][1]}


def cost_totals(facts, quantity):
    integer(quantity, "quantity", 1, 1000000)
    cost = integer(facts["unit_cost_cents"], "published unit cost", 1)
    if facts["currency"] != "USD":
        raise ValueError("only USD supported")
    return {
        "unit_cost_cents": cost,
        "total_cost_cents": cost * quantity,
        "cost_basis": "published ETL unit cost; no approved volume reduction",
    }


def risk_analysis(facts, quantity, config, model):
    integer(quantity, "scenario quantity", 1, 1000000)
    for key in ("customer_id", "project_id", "entity_id"):
        if facts[key] != config[key]:
            raise PermissionError("planning scope mismatch")
    planning = config["planning"]
    as_of = canonical_day(config["as_of"])
    if not visible(planning, as_of) or canonical_day(planning["yield_window_end"]) >= as_of:
        raise ValueError("planning inputs unavailable at analysis time")
    if planning["design_version"] != facts["design_version"]:
        raise ValueError("planning design is stale")
    if planning["base_order_quantity"] != facts["quantity"]:
        raise ValueError("planning quantity is stale")
    if canonical_day(model["cutoffs"]["evaluation_as_of"]) > as_of:
        raise ValueError("model artifact is newer than analysis time")
    for key in (
        "production_days_before_due",
        "gross_units_per_day",
        "allocated_quarter_units",
        "forecast_pickup_units",
    ):
        integer(planning[key], key, 1)
    for key in (
        "other_committed_units",
        "other_quarter_committed_units",
        "confirmed_pickup_units",
        "design_changes_30d",
    ):
        integer(planning[key], key)
    yield_bps = integer(planning["historical_yield_bps"], "historical yield", 1, 10000)
    days, gross = planning["production_days_before_due"], planning["gross_units_per_day"]
    committed = planning["other_committed_units"] + quantity
    usable_scaled = days * gross * yield_bps
    required_days = ceil_div(committed * 10000, gross * yield_bps)
    features = {
        "order_quantity": quantity,
        "capacity_load_ratio": committed * 10000 / usable_scaled,
        "schedule_slack_days": days - required_days,
        "recent_yield": yield_bps / 10000,
        "design_changes_30d": planning["design_changes_30d"],
        "allocation_utilization_ratio": (planning["other_quarter_committed_units"] + quantity)
        / planning["allocated_quarter_units"],
        "pickup_forecast_gap_ratio": max(
            0, planning["forecast_pickup_units"] - planning["confirmed_pickup_units"]
        )
        / planning["forecast_pickup_units"],
    }
    bounds = model.get("training_feature_bounds", {})
    outside = [
        name
        for name, value in features.items()
        if name in bounds and not bounds[name][0] <= value <= bounds[name][1]
    ]
    return {
        "features": features,
        "risk_score": 100 * score(model, features),
        "model_hash": digest(model),
        "model_status": "synthetic_unpromoted",
        "training_range_check": "available" if bounds else "unavailable",
        "outside_training_range": outside,
        "planning_hash": digest(planning),
        "line": planning["line"],
        "capacity_shortfall_units": max(0, ceil_div(committed * 10000 - usable_scaled, 10000)),
        "requires_capacity_review": committed * 10000 > usable_scaled,
        "assumption": "continuous production slots, common unit workload, aggregate line check; not a production scheduler",
    }


def quote_option(option_id, price, cost, quantity, minimum_margin_bps):
    integer(quantity, "quantity", 1, 1000000)
    integer(price, "unit price", 1)
    integer(cost, "unit cost", 1)
    revenue = price * quantity
    profit = (price - cost) * quantity
    return {
        "option_id": option_id,
        "unit_price_cents": price,
        "quantity": quantity,
        "revenue_cents": revenue,
        "total_cost_cents": cost * quantity,
        "gross_profit_cents": profit,
        "margin_bps": profit * 10000 // revenue,
        "margin_allowed": (price - cost) * 10000 >= minimum_margin_bps * price,
    }


def pricing_options(facts, quantity, cost, discount_bps, policy):
    integer(discount_bps, "discount", 1, 9999)
    floor = integer(policy["minimum_margin_bps"], "minimum margin", 0, 9999)
    current = integer(facts["unit_price_cents"], "published unit price", 1)
    requested = (current * (10000 - discount_bps) + 5000) // 10000
    minimum = ceil_div(cost * 10000, 10000 - floor)
    counter = max(requested, minimum)
    values = [("retain_price", current), ("customer_request", requested), ("counteroffer", counter)]
    return [quote_option(name, price, cost, quantity, floor) for name, price in values]
