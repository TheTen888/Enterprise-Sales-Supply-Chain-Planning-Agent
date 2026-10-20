from pipelines.etl.models import Event, Record


def transform_event(event: Event) -> Record:
    return Record(
        event,
        event.quantity * event.unit_cost_cents,
        event.quantity * event.unit_price_cents,
    )
