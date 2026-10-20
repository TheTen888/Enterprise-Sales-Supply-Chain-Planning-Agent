from app.repositories.warehouse import Warehouse
from pipelines.etl.models import Record


def load_candidate(warehouse: Warehouse, batch_id: str, records: list[Record]):
    warehouse.stage(batch_id, records)
