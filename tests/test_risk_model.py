import copy
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pipelines.etl.models import digest
from risk_model.dataset import (
    FEATURES,
    audit_dataset,
    build_dataset,
    canonical_day,
    features_at,
    label_for,
    latest,
    order_at,
    replay,
    split_dataset,
)
from risk_model.fixtures import generate, shifted
from risk_model.training import evaluate, matrix, metrics, rule_score, score, select_model
from scripts.run_risk_model import CONFIG


class RiskFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.config = json.loads(CONFIG.read_text())
        cls.raw = generate(cls.config)
        cls.warehouse, cls.batches = replay(Path(cls.temp.name), cls.raw)
        cls.rows, cls.rejected = build_dataset(cls.warehouse, cls.raw, cls.config)
        cls.splits, cls.purged = split_dataset(cls.rows, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()


class RiskDataTests(RiskFixture):
    def test_noncanonical_dates_cannot_bypass_time_comparisons(self):
        for value in ("20250120", "2025-W04-1", "2025-1-20", 20250120):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_day(value)

    def test_duplicate_outcomes_cannot_silently_replace_ground_truth(self):
        raw = copy.deepcopy(self.raw)
        raw["outcomes"].append(raw["outcomes"][0])
        with self.assertRaisesRegex(ValueError, "duplicate outcome"):
            build_dataset(self.warehouse, raw, self.config)

    def test_invalid_shipment_quantities_are_rejected(self):
        row = {"frozen_quantity": 12000, "frozen_due": "2025-01-20"}
        for quantity in (math.inf, math.nan, True, "12000", 12000.5):
            outcome = {
                "status": "completed",
                "closed_at": "2025-01-23",
                "deliveries": [
                    {"quantity": quantity, "date": "2025-01-20", "observed_at": "2025-01-21"}
                ],
            }
            with (
                self.subTest(quantity=quantity),
                self.assertRaisesRegex(ValueError, "invalid delivery"),
            ):
                label_for(row, outcome, "2025-02-01")

    def test_audit_detects_injected_future_evidence(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["lineage"]["plan"]["observed_at"] = "2099-01-01"
        with self.assertRaisesRegex(ValueError, "features_available_at_prediction"):
            audit_dataset(self.raw, rows, self.rejected, self.splits, self.purged, self.config)

    def test_audit_detects_unavailable_training_label(self):
        splits = copy.deepcopy(self.splits)
        splits["train"][0]["label_available_at"] = self.config["validation_start"]
        with self.assertRaisesRegex(ValueError, "labels_available_before_fitting_cutoffs"):
            audit_dataset(self.raw, self.rows, self.rejected, splits, self.purged, self.config)

    def test_renegotiated_due_date_does_not_hide_late_order(self):
        request = next(row for row in self.raw["orders"] if row["entity_id"] == "ORDER-41-05")
        row = features_at(self.warehouse, self.raw, request)
        outcome = next(
            row for row in self.raw["outcomes"] if row["entity_id"] == request["entity_id"]
        )
        self.assertEqual(label_for(row, outcome, self.config["evaluation_as_of"])[0], 1)
        later = next(
            plan
            for plan in self.raw["plans"]
            if plan["entity_id"] == request["entity_id"] and plan["version"] == 2
        )
        self.assertLessEqual(
            max(delivery["date"] for delivery in outcome["deliveries"]), later["due_date"]
        )
        with self.assertRaisesRegex(ValueError, "unmatured"):
            label_for(
                {**row, "frozen_due": later["due_date"]}, outcome, self.config["evaluation_as_of"]
            )

    def test_reuses_etl_without_missing_or_duplicate_events(self):
        counts = self.warehouse.counts()
        self.assertEqual(counts["processed_events"], len(self.raw["changes"]))
        self.assertEqual(counts["record_versions"], len(self.raw["changes"]))
        self.assertEqual(counts["quarantined_batches"], 0)
        self.assertTrue(all(row["status"] == "completed" for row in self.batches))

    def test_fixed_seed_reproducible(self):
        self.assertEqual(digest(self.raw), digest(generate(self.config)))

    def test_past_order_does_not_read_current_version(self):
        for request in self.raw["orders"]:
            order, _ = order_at(self.warehouse, request["entity_id"], request["prediction_at"])
            self.assertEqual(order["version"], 1)
        request = self.raw["orders"][0]
        later, _ = order_at(
            self.warehouse, request["entity_id"], shifted(request["prediction_at"], 4)
        )
        self.assertEqual(later["version"], 2)

    def test_effective_observed_and_available_times_independently_enforced(self):
        base = {
            "version": 1,
            "effective_at": "2025-01-01",
            "observed_at": "2025-01-01",
            "available_at": "2025-01-01",
        }
        for key in ("effective_at", "observed_at", "available_at"):
            with self.subTest(key=key):
                future = {**base, "version": 2, key: "2025-01-03"}
                self.assertEqual(latest([base, future], "2025-01-02")["version"], 1)

    def test_conflicting_plan_versions_rejected(self):
        plan = self.raw["plans"][0]
        with self.assertRaisesRegex(ValueError, "conflicting"):
            latest([plan, plan], self.raw["orders"][0]["prediction_at"])

    def test_future_plans_and_capacity_cannot_change_features(self):
        raw = copy.deepcopy(self.raw)
        request = raw["orders"][0]
        before = features_at(self.warehouse, raw, request)
        for plan in raw["plans"]:
            if plan["version"] == 2:
                plan["due_date"] = "2099-01-01"
                plan["committed_quarter_units"] = 999999999
        for capacity in raw["capacity"]:
            if capacity["version"] == 2:
                capacity["recent_yield"] = 0.01
        self.assertEqual(before, features_at(self.warehouse, raw, request))

    def test_changing_outcomes_does_not_change_features(self):
        raw = copy.deepcopy(self.raw)
        request = raw["orders"][2]
        before = features_at(self.warehouse, raw, request)
        raw["outcomes"] = []
        self.assertEqual(before, features_at(self.warehouse, raw, request))

    def test_wrong_ownership_is_rejected(self):
        raw = copy.deepcopy(self.raw)
        raw["plans"][0]["customer_id"] = "CUSTOMER-B"
        with self.assertRaisesRegex(ValueError, "ownership"):
            features_at(self.warehouse, raw, raw["orders"][0])

    def test_request_cannot_claim_other_customer_order(self):
        request = {**self.raw["orders"][0], "customer_id": "CUSTOMER-B"}
        with self.assertRaisesRegex(ValueError, "ownership"):
            features_at(self.warehouse, self.raw, request)

    def test_invalid_and_missing_capacity_are_not_imputed(self):
        request = self.raw["orders"][0]
        for field, invalid in (
            ("gross_capacity", 0),
            ("recent_yield", 0),
            ("committed_units", -1),
            ("recent_yield", math.nan),
            ("yield_window_end", request["prediction_at"]),
        ):
            raw = copy.deepcopy(self.raw)
            raw["capacity"][0][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                features_at(self.warehouse, raw, request)
        raw = copy.deepcopy(self.raw)
        raw["capacity"] = []
        with self.assertRaisesRegex(ValueError, "missing"):
            features_at(self.warehouse, raw, request)

    def test_allocation_zero_is_not_assumed_safe(self):
        raw = copy.deepcopy(self.raw)
        raw["plans"][0]["allocated_quarter_units"] = 0
        with self.assertRaises(ValueError):
            features_at(self.warehouse, raw, raw["orders"][0])

    def test_features_match_independent_business_calculations(self):
        request = self.raw["orders"][2]
        row = features_at(self.warehouse, self.raw, request)
        plan, capacity = row["lineage"]["plan"], row["lineage"]["capacity"]
        self.assertEqual(
            row["features"]["schedule_slack_days"],
            (date_value(plan["due_date"]) - date_value(plan["planned_finish"])).days,
        )
        self.assertAlmostEqual(
            row["features"]["capacity_load_ratio"],
            capacity["committed_units"] / capacity["gross_capacity"] / capacity["recent_yield"],
        )
        self.assertEqual(set(row["features"]), set(FEATURES))

    def test_shared_line_capacity_includes_other_projects(self):
        first = features_at(self.warehouse, self.raw, self.raw["orders"][0])
        second = features_at(self.warehouse, self.raw, self.raw["orders"][1])
        self.assertNotEqual(first["customer_id"], second["customer_id"])
        self.assertEqual(first["lineage"]["capacity"], second["lineage"]["capacity"])
        for capacity in self.raw["capacity"]:
            if capacity["version"] != 1:
                continue
            plans = [
                plan
                for plan in self.raw["plans"]
                if plan["version"] == 1
                and plan["line"] == capacity["line"]
                and plan["window"] == capacity["window"]
            ]
            quantities = sum(
                next(
                    change["payload"]["quantity"]
                    for change in self.raw["changes"]
                    if change["payload"]["entity_id"] == plan["entity_id"]
                    and change["payload"]["version"] == 1
                )
                for plan in plans
            )
            self.assertLessEqual(quantities, capacity["committed_units"])

    def test_label_uses_frozen_quantity_and_exact_due_boundary(self):
        row = {"frozen_quantity": 12000, "frozen_due": "2025-01-20"}
        outcome = {
            "status": "completed",
            "closed_at": "2025-01-23",
            "deliveries": [
                {"quantity": 4000, "date": "2025-01-14", "observed_at": "2025-01-15"},
                {"quantity": 8000, "date": "2025-01-20", "observed_at": "2025-01-21"},
            ],
        }
        self.assertEqual(label_for(row, outcome, "2025-02-01")[0], 0)
        outcome["deliveries"][1]["date"] = "2025-01-21"
        self.assertEqual(label_for(row, outcome, "2025-02-01")[0], 1)

    def test_later_extra_quantity_does_not_relabel_original_commitment(self):
        row = {"frozen_quantity": 12000, "frozen_due": "2025-01-20"}
        outcome = {
            "status": "completed",
            "closed_at": "2025-01-30",
            "deliveries": [
                {"quantity": 12000, "date": "2025-01-20", "observed_at": "2025-01-21"},
                {"quantity": 2000, "date": "2025-01-27", "observed_at": "2025-01-28"},
            ],
        }
        self.assertEqual(label_for(row, outcome, "2025-02-01")[0], 0)

    def test_unresolved_cancelled_incomplete_and_unmatured_not_negative(self):
        row = {"frozen_quantity": 12000, "frozen_due": "2025-01-20"}
        outcome = {"status": "completed", "closed_at": "2025-01-30", "deliveries": []}
        for status in ("open", "cancelled", "completed"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                label_for(row, {**outcome, "status": status}, "2025-02-01")
        with self.assertRaisesRegex(ValueError, "unmatured"):
            label_for(row, outcome, "2025-01-25")

    def test_temporal_split_purges_unavailable_labels(self):
        self.assertGreater(len(self.purged), 0)
        all_ids = []
        for name, cutoff in (
            ("train", "validation_start"),
            ("validation", "test_start"),
            ("test", "evaluation_as_of"),
        ):
            for row in self.splits[name]:
                self.assertLess(row["label_available_at"], self.config[cutoff])
                all_ids.append(row["entity_id"])
        self.assertEqual(len(all_ids), len(set(all_ids)))
        self.assertLess(
            max(row["prediction_at"] for row in self.splits["train"]),
            min(row["prediction_at"] for row in self.splits["validation"]),
        )
        self.assertLess(
            max(row["prediction_at"] for row in self.splits["validation"]),
            min(row["prediction_at"] for row in self.splits["test"]),
        )

    def test_censored_rows_are_accounted_for(self):
        self.assertEqual(len(self.rows) + len(self.rejected), len(self.raw["orders"]))
        self.assertEqual(
            {row["reason"] for row in self.rejected},
            {"censored_open", "censored_cancelled", "unmatured_label"},
        )


def date_value(value):
    from datetime import date

    return date.fromisoformat(value)


@unittest.skipUnless(
    importlib.util.find_spec("sklearn"), "install requirements-risk.txt for ML checks"
)
class RiskTrainingTests(RiskFixture):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pipeline, cls.model, cls.selection = select_model(
            cls.splits["train"], cls.splits["validation"]
        )

    def test_scaler_fit_only_on_train(self):
        train = matrix(self.splits["train"])
        expected = [sum(row[index] for row in train) / len(train) for index in range(len(FEATURES))]
        for actual, value in zip(self.model["mean"], expected, strict=True):
            self.assertAlmostEqual(actual, value)

    def test_holdout_changes_cannot_affect_selection_or_parameters(self):
        poisoned = copy.deepcopy(self.splits)
        for row in poisoned["test"]:
            row["label"] = 1 - row["label"]
            row["features"]["order_quantity"] = 10**12
        _, model, selection = select_model(poisoned["train"], poisoned["validation"])
        self.assertEqual(model, self.model)
        self.assertEqual(selection, self.selection)

    def test_exported_score_matches_sklearn(self):
        report = evaluate(self.pipeline, self.model, self.splits, 0.25)
        self.assertLess(report["export_max_abs_error"], 1e-10)
        self.assertEqual(report["rule_baseline"]["alerts"], report["logistic_model"]["alerts"])

    def test_full_scoring_pool_retains_orders_without_mature_labels(self):
        pool = [
            features_at(self.warehouse, self.raw, request)
            for request in self.raw["orders"]
            if request["prediction_at"] >= self.config["test_start"]
        ]
        report = evaluate(self.pipeline, self.model, self.splits, 0.25, pool)
        for name in ("rule_baseline", "logistic_model"):
            result = report[name]
            self.assertEqual(result["orders"], 144)
            self.assertEqual(result["labeled_orders"], 138)
            self.assertEqual(result["unlabeled_orders"], 6)
            self.assertEqual(result["alerts"], 36)
            self.assertEqual(result["labeled_alerts"] + result["unlabeled_alerts"], 36)

    def test_evaluation_cannot_omit_a_labeled_test_order(self):
        with self.assertRaisesRegex(ValueError, "omits labeled"):
            evaluate(self.pipeline, self.model, self.splits, 0.25, self.splits["test"][1:])

    def test_alert_metrics_match_hand_counted_case(self):
        rows = [
            {"entity_id": str(index), "prediction_at": "2025-01-01", "label": label}
            for index, label in enumerate([1, 0, 1, 0])
        ]
        result = metrics(rows, [0.9, 0.8, 0.7, 0.1], 0.5)
        self.assertEqual(result["alerts"], 2)
        self.assertEqual(result["true_positives"], 1)
        self.assertEqual(result["precision_on_labeled_alerts"], 0.5)
        self.assertEqual(result["recall_at_budget"], 0.5)

    def test_score_rejects_extra_label_and_malformed_export(self):
        features = self.splits["test"][0]["features"]
        with self.assertRaisesRegex(ValueError, "contract"):
            score(self.model, {**features, "actual_delivery": 1})
        for invalid in (math.nan, math.inf):
            with self.assertRaises(ValueError):
                score(self.model, {**features, "order_quantity": invalid})
        model = copy.deepcopy(self.model)
        model["scale"][0] = 0
        with self.assertRaises(ValueError):
            score(model, features)

    def test_rule_is_fixed_index_not_claimed_probability(self):
        for row in self.rows:
            self.assertGreaterEqual(rule_score(row["features"]), 0)
            self.assertLessEqual(rule_score(row["features"]), 1)

    def test_unlabeled_high_score_still_consumes_alert_budget(self):
        rows = [
            {"entity_id": str(index), "prediction_at": "2025-01-01", "label": label}
            for index, label in enumerate([None, 1, 0, 1])
        ]
        result = metrics(rows, [0.9, 0.8, 0.7, 0.1], 0.25)
        self.assertEqual(result["alerts"], 1)
        self.assertEqual(result["unlabeled_alerts"], 1)
        self.assertEqual(result["true_positives"], 0)
        self.assertEqual(result["recall_at_budget"], 0)
        self.assertIsNone(result["precision_on_labeled_alerts"])
        self.assertEqual(result["precision_bounds_all_alerts"], [0, 1])

    def test_alert_selection_does_not_depend_on_outcomes(self):
        rows = [
            {"entity_id": str(index), "prediction_at": "2025-01-01", "label": label}
            for index, label in enumerate([None, 1, 0, 1])
        ]
        before = metrics(rows, [0.9, 0.8, 0.7, 0.1], 0.25)
        rows[0]["label"] = 0
        after = metrics(rows, [0.9, 0.8, 0.7, 0.1], 0.25)
        self.assertEqual(before["alerts"], after["alerts"])
        self.assertEqual(after["true_positives"], 0)
        self.assertEqual(after["false_positives"], 1)

    def test_scoring_rejects_impossible_business_features(self):
        original = self.splits["test"][0]["features"]
        for name, value in (
            ("order_quantity", 0),
            ("order_quantity", True),
            ("recent_yield", 1.2),
            ("design_changes_30d", 1.5),
            ("pickup_forecast_gap_ratio", -0.1),
            ("capacity_load_ratio", -1),
        ):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                score(self.model, {**original, name: value})

    def test_exported_cli_scores_without_installed_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = self.splits["test"][0]
            (root / "model.json").write_text(json.dumps(self.model))
            (root / "input.json").write_text(
                json.dumps([{key: row[key] for key in ("entity_id", "prediction_at", "features")}])
            )
            subprocess.run(
                [
                    sys.executable,
                    "-S",
                    "-m",
                    "scripts.score_risk_model",
                    "--model",
                    str(root / "model.json"),
                    "--input",
                    str(root / "input.json"),
                    "--output",
                    str(root / "scores.json"),
                ],
                check=True,
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent,
            )
            self.assertAlmostEqual(
                json.loads((root / "scores.json").read_text())[0]["risk_score"],
                100 * score(self.model, row["features"]),
            )
