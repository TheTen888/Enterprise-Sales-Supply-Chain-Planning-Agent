from itertools import product


def generate_cases():
    return [
        {
            "id": f"matrix-{days}-{quantity}-{factory}",
            "request": {
                "prompt": "Prepare a quote",
                "requested_days": days,
                "quantity": quantity,
                "preferred_factory": factory,
            },
            "expected_route": "quote",
            "oracle": {
                "minimum_days": 28,
                "unit_cost_cents": 1300,
                "factory_available": {"PLANT-A": 2000, "PLANT-B": 40000},
            },
            "label_status": "rule_generated_not_independently_reviewed",
        }
        for days, quantity, factory in product(
            [14, 28, 35], [1000, 12000, 50000], ["PLANT-A", "PLANT-B"]
        )
    ]
