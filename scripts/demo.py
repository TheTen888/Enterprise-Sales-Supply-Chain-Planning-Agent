import argparse
import json
import uuid
from pathlib import Path

from agent.service import Service
from config.contracts import Scope
from data_pipeline.ingestion import RateLimitError
from evaluation.eval_pipeline import evaluate
from mock_data.generator import generate


def run(root):
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    root = destination / f"run-{uuid.uuid4().hex[:10]}"
    generate(root / "source")
    service = Service(root)
    manifest = json.loads((service.source / "manifest.json").read_text())
    try:
        service.ingestion.ingest(service.source, manifest[0], simulate_rate_limit=True)
    except RateLimitError:
        pass
    recovery = service.ingestion.ingest(service.source, manifest[0])
    service.ingest_all()
    scope = Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A")
    service.memory.store_preference(
        scope, "shipping_term", "FOB Port Alpha", "MAIL-001:v1", confirmed=True
    )
    request = {"prompt": "Prepare a discounted quote", "quantity": 12000}
    original = service.run("demo-manager", scope, request)
    revised = service.run("demo-manager", scope, {**request, "quantity": 50000})
    report = evaluate(service)
    (root / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    (destination / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    walkthrough = {"recovery": recovery, "original": original, "revised": revised}
    (root / "walkthrough.json").write_text(json.dumps(walkthrough, indent=2) + "\n")
    (destination / "walkthrough.json").write_text(json.dumps(walkthrough, indent=2) + "\n")
    print(
        json.dumps(
            {
                "cases": report["cases"],
                "passed": report["passed"],
                "metrics": report["metrics"],
                "original": original["artifact"]["result"],
                "revised_status": revised["artifact"]["status"],
                "report": str(root / "evaluation.json"),
                "production_approved": False,
            },
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runtime")
    report = run(parser.parse_args().root)
    raise SystemExit(0 if report["passed"] == report["cases"] else 1)
