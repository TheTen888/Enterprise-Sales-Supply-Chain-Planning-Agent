from app.repositories.source import Source
from pipelines.etl.models import Change


def extract_changes(source: Source, cursor: int, batch_size: int) -> list[Change]:
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise ValueError("batch_size must be a positive integer")
    return source.read_after(cursor, batch_size)
