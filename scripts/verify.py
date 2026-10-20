import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import sys
import tokenize
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Verify local ETL, scoped retrieval and synthetic evidence"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--risk", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output if args.output.is_absolute() else root / args.output
    output.mkdir(parents=True, exist_ok=True)
    comments, docstrings, hashes = [], [], {}
    for directory in ["app", "pipelines", "rag", "risk_model", "integrations", "scripts", "tests"]:
        for path in sorted((root / directory).rglob("*.py")):
            source = path.read_text()
            name = str(path.relative_to(root))
            hashes[name] = hashlib.sha256(source.encode()).hexdigest()
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type == tokenize.COMMENT:
                    comments.append([name, token.start[0]])
            for node in ast.walk(ast.parse(source)):
                if isinstance(
                    node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
                ) and ast.get_docstring(node):
                    docstrings.append(name)
    if comments or docstrings:
        raise RuntimeError("code comments/docstrings found")
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    (output / "unit-tests.txt").write_text(tests.stderr)
    if tests.returncode:
        print(tests.stderr, file=sys.stderr)
        raise SystemExit(tests.returncode)
    skipped = int(match.group(1)) if (match := re.search(r"skipped=(\d+)", tests.stderr)) else 0
    if args.risk and skipped:
        raise RuntimeError("full risk verification requires zero skipped tests")
    local_demo = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.run_local",
            "--output",
            str(args.output),
            "--json",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if local_demo.returncode:
        print(local_demo.stdout, file=sys.stderr)
        print(local_demo.stderr, file=sys.stderr)
        raise SystemExit(local_demo.returncode)
    demo = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.demo",
            "--backlog-rows",
            "5000",
            "--output",
            str(args.output),
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if demo.returncode:
        print(demo.stderr, file=sys.stderr)
        raise SystemExit(demo.returncode)
    experiments = json.loads(demo.stdout)
    load = subprocess.run(
        [sys.executable, "-m", "scripts.load_eval", "--output", str(args.output)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if load.returncode:
        print(load.stdout, file=sys.stderr)
        print(load.stderr, file=sys.stderr)
        raise SystemExit(load.returncode)
    load_evaluation = json.loads(load.stdout)
    walkthrough = subprocess.run(
        [sys.executable, "-m", "scripts.order_walkthrough", "--output", str(args.output)],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if walkthrough.returncode:
        print(walkthrough.stdout, file=sys.stderr)
        print(walkthrough.stderr, file=sys.stderr)
        raise SystemExit(walkthrough.returncode)
    rag_demo = subprocess.run(
        [sys.executable, "-m", "scripts.run_rag", "--output", str(args.output), "--json"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if rag_demo.returncode:
        print(rag_demo.stdout, file=sys.stderr)
        print(rag_demo.stderr, file=sys.stderr)
        raise SystemExit(rag_demo.returncode)
    rag_eval = subprocess.run(
        [sys.executable, "-m", "scripts.eval_rag", "--output", str(args.output), "--full"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if rag_eval.returncode:
        print(rag_eval.stdout, file=sys.stderr)
        print(rag_eval.stderr, file=sys.stderr)
        raise SystemExit(rag_eval.returncode)
    rag_evaluation = json.loads(rag_eval.stdout)
    additional = {}
    for name, module in (
        ("api_contracts", "scripts.demo_api_contracts"),
        ("rag_walkthrough", "scripts.review_rag"),
    ):
        completed = subprocess.run(
            [sys.executable, "-m", module, "--output", str(args.output)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            print(completed.stderr, file=sys.stderr)
            print(completed.stdout, file=sys.stderr)
            raise SystemExit(completed.returncode)
        additional[name] = json.loads(completed.stdout)
    if args.risk:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.run_risk_model", "--output", str(output)],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            print(completed.stderr, file=sys.stderr)
            raise SystemExit(completed.returncode)
        risk_run = json.loads(completed.stdout)
        additional["risk_model"] = json.loads(Path(risk_run["report"]).read_text())
    result = {
        "passed": True,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "unit_tests": {
            "passed": True,
            "count": int(re.search(r"Ran (\d+) tests", tests.stderr).group(1)),
            "skipped": skipped,
        },
        "code_comments": comments,
        "code_docstrings": docstrings,
        "local_demo": json.loads(local_demo.stdout),
        "fault_experiments": experiments,
        "load_evaluation": load_evaluation,
        "order_walkthrough": json.loads(walkthrough.stdout),
        "rag_demo": json.loads(rag_demo.stdout),
        "rag_evaluation": rag_evaluation,
        **additional,
        "source_sha256": hashes,
        "scope": "Local synthetic ETL, scoped keyword retrieval and optional risk-model evaluation; no cloud services or LLM calls",
    }
    destination = root / "docs/evidence/verification.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2) + "\n")
    (destination.parent / "rag-evaluation.json").write_text(
        json.dumps(rag_evaluation, indent=2) + "\n"
    )
    for name, value in additional.items():
        (destination.parent / (name.replace("_", "-") + ".json")).write_text(
            json.dumps(value, indent=2) + "\n"
        )
    if args.full:
        print(json.dumps(result, indent=2))
    else:
        print(
            json.dumps(
                {
                    "passed": result["passed"],
                    "python": result["python"],
                    "unit_tests": result["unit_tests"],
                    "local_demo": result["local_demo"]["passed"],
                    "fault_experiments": len(experiments["experiments"]),
                    "load_scenarios": len(load_evaluation["scenarios"]),
                    "order_walkthrough": result["order_walkthrough"]["all_passed"],
                    "rag_cases": rag_evaluation["retrieval"]["case_count"],
                    "rag_lifecycle_experiments": len(rag_evaluation["lifecycle"]),
                    "rag_evaluation": rag_evaluation["passed"],
                    "condition_labeled_cases": rag_evaluation["retrieval"][
                        "condition_labeled_cases"
                    ],
                    "mean_condition_coverage": rag_evaluation["retrieval"][
                        "mean_condition_coverage"
                    ],
                    "discount_example_condition_coverage": additional["rag_walkthrough"][
                        "condition_comparison"
                    ]["bounded_document_context"]["coverage"],
                    "api_contracts": additional["api_contracts"]["passed"],
                    "rag_walkthrough": additional["rag_walkthrough"]["passed"],
                    "code_comments": len(comments),
                    "code_docstrings": len(docstrings),
                    "risk_model": "risk_model" in additional,
                    "evidence": str(destination.relative_to(root)),
                    "demo_report": str(Path(result["local_demo"]["workspace"]) / "report.json"),
                    "rag_report": str(
                        Path(result["rag_demo"]["workspace"]) / "evidence-report.txt"
                    ),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
