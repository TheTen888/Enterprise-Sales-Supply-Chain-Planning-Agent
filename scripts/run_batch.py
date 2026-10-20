import argparse
import json
import sys
from pathlib import Path

from app.repositories.source import Source
from app.repositories.warehouse import Warehouse
from pipelines.etl.models import Fault, InjectedFailure
from pipelines.etl.pipeline import IncrementalETL
from pipelines.etl.policy import BatchPolicy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--warehouse", type=Path, required=True)
    parser.add_argument("--source-name", default="internal-db")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--adaptive", action="store_true")
    parser.add_argument("--retry-quarantined", action="store_true")
    parser.add_argument("--fault-after", choices=["after_stage", "during_publish", "after_publish"])
    args = parser.parse_args()
    pipeline = IncrementalETL(
        Source(args.source, args.source_name),
        Warehouse(args.warehouse),
        args.batch_size,
        policy=BatchPolicy() if args.adaptive else None,
    )
    try:
        result = pipeline.run_once(Fault(args.fault_after), args.retry_quarantined)
    except InjectedFailure as exc:
        print(json.dumps({"status": "injected_failure", "phase": str(exc)}))
        return 70
    print(json.dumps(result, indent=2))
    return 2 if result["status"] == "quarantined" else 0


if __name__ == "__main__":
    sys.exit(main())
