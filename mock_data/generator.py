import argparse
import json
from pathlib import Path

from openpyxl import Workbook

from config.contracts import Document


def generate(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, claimed in [("bom_quote_v1.xlsx", 1300), ("bom_quote_invalid.xlsx", 1200)]:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "BOM"
        for row in [
            ["Component", "Units", "Unit Cost Cents", "Extended Cost Cents"],
            ["Material", 1, 800, "=B2*C2"],
            ["Assembly", 1, 300, "=B3*C3"],
            ["Required Inspection", 1, 200, "=B4*C4"],
            ["Total", None, None, "=SUM(D2:D4)"],
            ["Claimed Total", None, None, claimed],
            ["Discount Band", None, None, "=IF(D5>=1000,5,0)"],
        ]:
            sheet.append(row)
        workbook.save(root / name)
    documents = []
    for version, status, days in [(1, "deprecated", 14), (2, "active", 28)]:
        name = f"ECN_001_v{version}_{status}.md"
        (root / name).write_text(
            f"# ECN-001 | PART-001 | Version {version}\n\n"
            f"Status: {status}. Minimum lead time: {days} days.\n\n"
            "The latest material revision requires inspection. Inspection cannot be removed to fund a discount.\n",
            encoding="utf-8",
        )
        documents.append(
            Document(
                document_id="ECN-001",
                customer_id="CUSTOMER-A",
                project_id="PROJECT-A",
                version=version,
                status=status,
                kind="ecn",
                path=name,
                part_id="PART-001",
                lead_days=days,
            ).model_dump()
        )
    (root / "customer_email.txt").write_text(
        "Please quote 12,000 units of PART-001 with a 5% discount and delivery in 14 days.\n\n"
        "We may increase next quarter's volume, but that volume is not signed or committed.\n\n"
        "Our confirmed shipping preference is FOB Port Alpha.\n",
        encoding="utf-8",
    )
    (root / "other_customer.txt").write_text(
        "Private CUSTOMER-B terms. Unit cost: 999 cents.\n", encoding="utf-8"
    )
    for doc_id, kind, path, customer, project in [
        ("BOM-001", "bom", "bom_quote_v1.xlsx", "CUSTOMER-A", "PROJECT-A"),
        ("MAIL-001", "email", "customer_email.txt", "CUSTOMER-A", "PROJECT-A"),
        ("MAIL-PRIVATE", "email", "other_customer.txt", "CUSTOMER-B", "PROJECT-B"),
    ]:
        documents.append(
            Document(
                document_id=doc_id,
                customer_id=customer,
                project_id=project,
                version=1,
                kind=kind,
                path=path,
                part_id="PART-001",
            ).model_dump()
        )
    capacity = [
        {
            "factory_id": "PLANT-A",
            "quarter": "2026-Q4",
            "capacity_units": 100000,
            "committed_units": 98000,
            "process_days": 14,
        },
        {
            "factory_id": "PLANT-B",
            "quarter": "2026-Q4",
            "capacity_units": 80000,
            "committed_units": 40000,
            "process_days": 21,
        },
    ]
    (root / "manifest.json").write_text(json.dumps(documents, indent=2) + "\n")
    (root / "factory_capacity.json").write_text(json.dumps(capacity, indent=2) + "\n")
    return documents


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="runtime/source")
    generate(parser.parse_args().output)
