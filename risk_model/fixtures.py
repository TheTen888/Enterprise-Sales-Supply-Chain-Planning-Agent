import math
import random
from datetime import date, timedelta

from scripts.fixtures import order_event


def shifted(day, days):
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


def generate(config):
    rng = random.Random(config["seed"])
    result = {"orders": [], "changes": [], "plans": [], "capacity": [], "outcomes": []}
    for week in range(config["weeks"]):
        prediction = shifted(config["start"], week * 7)
        capacities = {}
        for line in ["LINE-1", "LINE-2"]:
            gross = rng.randint(160, 220) * 1000
            recent_yield = round(rng.uniform(0.78, 0.99), 3)
            load = rng.uniform(0.65, 1.4)
            capacity = {
                "line": line,
                "window": prediction,
                "window_end": shifted(prediction, 14),
                "version": 1,
                "effective_at": shifted(prediction, -2),
                "observed_at": shifted(prediction, -1),
                "available_at": prediction,
                "yield_window_end": shifted(prediction, -2),
                "gross_capacity": gross,
                "recent_yield": recent_yield,
                "committed_units": round(gross * recent_yield * load),
            }
            capacities[line] = capacity
            result["capacity"].append(capacity)
            result["capacity"].append(
                {
                    **capacity,
                    "version": 2,
                    "committed_units": gross // 2,
                    "effective_at": shifted(prediction, 2),
                    "observed_at": shifted(prediction, 2),
                    "available_at": shifted(prediction, 3),
                }
            )
        for index in range(config["orders_per_week"]):
            entity = f"ORDER-{week:02d}-{index:02d}"
            customer = "CUSTOMER-A" if index % 2 == 0 else "CUSTOMER-B"
            project = "PROJECT-A" if index % 2 == 0 else "PROJECT-B"
            line = f"LINE-{1 + (index // 2) % 2}"
            quantity = rng.randint(6, 12) * 1000
            slack = rng.randint(-5, 8)
            changes = rng.randint(0, 4)
            allocated = rng.randint(60, 150) * 1000
            quarter_committed = round(allocated * rng.uniform(0.6, 1.3))
            forecast = rng.randint(15, 40) * 1000
            pickup = round(forecast * rng.uniform(0.4, 1.15))
            due = shifted(prediction, 14)
            plan = {
                "entity_id": entity,
                "customer_id": customer,
                "project_id": project,
                "line": line,
                "window": prediction,
                "version": 1,
                "effective_at": shifted(prediction, -2),
                "observed_at": shifted(prediction, -1),
                "available_at": prediction,
                "due_date": due,
                "planned_finish": shifted(due, -slack),
                "design_changes_30d": changes,
                "allocated_quarter_units": allocated,
                "committed_quarter_units": quarter_committed,
                "forecast_pickup_units": forecast,
                "confirmed_pickup_units": pickup,
            }
            result["orders"].append(
                {
                    "entity_id": entity,
                    "customer_id": customer,
                    "project_id": project,
                    "prediction_at": prediction,
                }
            )
            payload = order_event(
                entity,
                quantity=quantity,
                customer_id=customer,
                project_id=project,
                unit_cost="13.00",
                unit_price="15.00",
            )
            result["changes"].extend(
                [
                    {
                        "payload": payload,
                        "effective_at": shifted(prediction, -2),
                        "observed_at": shifted(prediction, -1),
                        "available_at": prediction,
                    },
                    {
                        "payload": order_event(
                            entity,
                            version=2,
                            quantity=quantity + 2000,
                            customer_id=customer,
                            project_id=project,
                        ),
                        "effective_at": shifted(prediction, -2),
                        "observed_at": shifted(prediction, 3),
                        "available_at": shifted(prediction, 4),
                    },
                ]
            )
            result["plans"].extend(
                [
                    plan,
                    {
                        **plan,
                        "version": 2,
                        "due_date": shifted(due, 7),
                        "effective_at": shifted(prediction, 5),
                        "observed_at": shifted(prediction, 5),
                        "available_at": shifted(prediction, 6),
                    },
                ]
            )
            capacity = capacities[line]
            load = capacity["committed_units"] / (
                capacity["gross_capacity"] * capacity["recent_yield"]
            )
            gap = max(0, forecast - pickup) / forecast
            logit = (
                -1.4
                + 3.0 * (load - 1)
                - 0.26 * slack
                + 0.35 * changes
                + 1.4 * gap
                + 1.1 * (quarter_committed / allocated - 1)
                + 1.8 * (0.92 - capacity["recent_yield"])
            )
            late = rng.random() < 1 / (1 + math.exp(-logit))
            completion = shifted(due, rng.randint(1, 9) if late else -rng.randint(0, 5))
            status = "open" if week % 13 == 0 and index == 0 else "completed"
            if week % 13 == 0 and index == 1:
                status = "cancelled"
            result["outcomes"].append(
                {
                    "entity_id": entity,
                    "status": status,
                    "closed_at": shifted(max(due, completion), 2 if index % 11 else 35),
                    "deliveries": [
                        {
                            "date": shifted(due, -6),
                            "observed_at": shifted(due, -5),
                            "quantity": quantity // 3,
                        },
                        {
                            "date": completion,
                            "observed_at": shifted(completion, 1),
                            "quantity": quantity - quantity // 3,
                        },
                    ]
                    if status == "completed"
                    else [],
                }
            )
    return result
