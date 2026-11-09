import json

from evaluation.eval_pipeline import evaluate
from evaluation.gates import release_gates
from evaluation.judge import JudgeVerdict, review_labels


class FakeJudge:
    def __init__(self, passed=True):
        self.passed = passed

    def with_structured_output(self, schema):
        return self

    def invoke(self, messages):
        return JudgeVerdict(
            passed=self.passed,
            business_consistent=self.passed,
            issues=[] if self.passed else ["Contradiction"],
        )


def test_no_key_means_pending_never_automatic_pass(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = review_labels(tmp_path, "judge")
    assert report["review_status"] == "pending"
    assert report["logical_model_calls"] == 0
    assert len(report["rows"]) == 23


def test_mock_judge_cannot_unlock_independent_review(service):
    review = review_labels(service.root, "other-model", FakeJudge())
    assert all(row["review_status"] == "passed" for row in review["rows"])
    assert review["review_status"] != "passed"
    report = evaluate(service)
    assert report["release"]["independent_labels_reviewed"] is False


def test_judge_detects_reported_conflicts(tmp_path):
    review = review_labels(tmp_path, "judge", FakeJudge(False))
    assert all(row["review_status"] == "failed" for row in review["rows"])


def test_rule_consistency_rejects_bad_label_even_if_judge_accepts(tmp_path, monkeypatch):
    import evaluation.judge as module

    case = {
        "id": "bad",
        "request": {"prompt": "Prepare quote"},
        "expected_route": "quote",
        "oracle": {"unit_cost_cents": 1, "minimum_days": 14, "factory_available": {}},
    }
    monkeypatch.setattr(module, "dataset", lambda: [case])
    review = review_labels(tmp_path, "judge", FakeJudge())
    assert review["rows"][0]["rule_consistency"] is False
    assert review["rows"][0]["review_status"] == "failed"


def test_local_success_does_not_open_production(service):
    report = evaluate(service)
    assert report["release"]["local_acceptance_passed"]
    assert not report["release"]["production_approved"]


def test_stale_qualification_evidence_cannot_open_gate(service):
    report = evaluate(service)
    for name in ["label-review.json", "live-evaluation.json", "deployment-checks.json"]:
        (service.root / name).write_text(
            json.dumps(
                {
                    "review_status": "passed",
                    "production_approved": True,
                    "implementation_hash": "stale",
                }
            )
        )
    gate = release_gates(report, service.root)
    assert not gate["production_approved"]
    assert len(gate["blockers"]) == 3


def test_gate_requires_all_current_evidence_not_just_local_success(service):
    from evaluation.gates import implementation_hash
    from evaluation.judge import dataset, dataset_hash

    report = evaluate(service)
    labels = {
        "review_status": "passed",
        "mode": "llm",
        "model_separate_from_agent": True,
        "dataset_hash": dataset_hash(),
        "logical_model_calls": 23,
        "reference_review": {
            "status": "passed",
            "dataset_hash": dataset_hash(),
            "reference_type": "project_authored_expected_rules",
        },
        "rows": [{"case_id": case["id"], "review_status": "passed"} for case in dataset()],
    }
    live = {
        "dataset_hash": dataset_hash(),
        "implementation_hash": implementation_hash(),
        "cases": 23,
        "passed": 23,
        "all_real_llm": True,
        "all_semantic": True,
        "no_fallbacks": True,
        "tracing_verified": True,
    }
    deployment = {
        "implementation_hash": implementation_hash(),
        "http_contract_passed": True,
        "container_arm64_passed": True,
        "identity_access_checked": True,
        "aws_runtime_verified": True,
    }
    for name, data in [
        ("label-review.json", labels),
        ("live-evaluation.json", live),
        ("deployment-checks.json", deployment),
    ]:
        (service.root / name).write_text(json.dumps(data))
    assert release_gates(report, service.root)["production_approved"]
    live["no_fallbacks"] = False
    (service.root / "live-evaluation.json").write_text(json.dumps(live))
    assert not release_gates(report, service.root)["production_approved"]
