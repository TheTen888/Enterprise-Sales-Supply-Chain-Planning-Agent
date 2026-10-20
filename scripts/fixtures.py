def order_event(entity_id: str = "ORDER-001-L1", version: int = 1, **overrides) -> dict:
    value = {
        "event_id": f"{entity_id}-v{version}",
        "entity_id": entity_id,
        "version": version,
        "operation": "upsert",
        "customer_id": "CUSTOMER-A",
        "project_id": "PROJECT-A",
        "currency": "USD",
        "quantity": 100,
        "unit_cost": "12.50",
        "unit_price": "15.00",
        "design_version": "D1",
    }
    value.update(overrides)
    return value
