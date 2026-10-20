from decimal import Decimal, InvalidOperation

from pipelines.etl.models import Event, Record, ValidationError, digest


def required_text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
    ):
        raise ValidationError(f"{key}: non-empty, trimmed text required")
    return value


def positive_integer(payload: dict, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 1_000_000_000:
        raise ValidationError(f"{key}: integer in 1..1000000000 required")
    return value


def cents(payload: dict, key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValidationError(f"{key}: decimal string required")
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number > Decimal("10000000"):
            raise ValidationError(f"{key}: finite amount in 0..10000000 required")
        scaled = number * 100
        if scaled != scaled.to_integral_value():
            raise ValidationError(f"{key}: at most two decimal places required")
        return int(scaled)
    except InvalidOperation as exc:
        raise ValidationError(f"{key}: invalid decimal") from exc


def validate_change(payload: dict, source: str, scope: tuple | None) -> Event:
    if not isinstance(payload, dict):
        raise ValidationError("object payload required")
    entity = required_text(payload, "entity_id")
    customer = required_text(payload, "customer_id")
    project = required_text(payload, "project_id")
    if scope is None or scope != (customer, project):
        raise ValidationError("trusted customer/project ownership does not match")
    event_id = required_text(payload, "event_id")
    version = positive_integer(payload, "version")
    operation = required_text(payload, "operation")
    if operation not in {"upsert", "delete"}:
        raise ValidationError("operation must be upsert or delete")
    currency, quantity, cost, price, design = "USD", 0, 0, 0, ""
    if operation == "upsert":
        currency = required_text(payload, "currency")
        if currency != "USD":
            raise ValidationError("prototype contract accepts USD only")
        quantity = positive_integer(payload, "quantity")
        cost = cents(payload, "unit_cost")
        price = cents(payload, "unit_price")
        design = required_text(payload, "design_version")
    normalized = {
        "entity_id": entity,
        "version": version,
        "operation": operation,
        "customer_id": customer,
        "project_id": project,
        "currency": currency,
        "quantity": quantity,
        "unit_cost_cents": cost,
        "unit_price_cents": price,
        "design_version": design,
    }
    return Event(
        source,
        event_id,
        entity,
        version,
        operation,
        customer,
        project,
        currency,
        quantity,
        cost,
        price,
        design,
        digest(normalized),
    )


def validate_record(record: Record):
    event = record.event
    if record.extended_cost_cents != event.quantity * event.unit_cost_cents:
        raise ValidationError("extended cost mismatch")
    if record.extended_price_cents != event.quantity * event.unit_price_cents:
        raise ValidationError("extended price mismatch")
    if max(record.extended_cost_cents, record.extended_price_cents) >= 2**63:
        raise ValidationError("amount exceeds SQLite integer range")
