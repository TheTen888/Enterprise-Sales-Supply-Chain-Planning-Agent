import math
from collections import defaultdict

from pipelines.etl.models import digest
from risk_model.dataset import FEATURES


def matrix(rows):
    return [[row["features"][name] for name in FEATURES] for row in rows]


def rule_score(features):
    def clip(value):
        return max(0, min(1, value))

    return (
        0.45 * clip((features["capacity_load_ratio"] - 0.8) / 0.5)
        + 0.35 * clip((3 - features["schedule_slack_days"]) / 10)
        + 0.20 * clip((1 - features["recent_yield"]) / 0.2)
    )


def select_model(train, validation):
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    candidates = []
    best = None
    for strength in [0.1, 1.0, 10.0]:
        pipeline = make_pipeline(
            StandardScaler(), LogisticRegression(C=strength, max_iter=1000, random_state=0)
        )
        pipeline.fit(matrix(train), [row["label"] for row in train])
        ap = float(
            average_precision_score(
                [row["label"] for row in validation],
                pipeline.predict_proba(matrix(validation))[:, 1],
            )
        )
        candidates.append({"C": strength, "validation_average_precision": ap})
        if best is None or ap > best[0]:
            best = ap, pipeline, strength
    pipeline = best[1]
    scaler, classifier = pipeline.steps[0][1], pipeline.steps[1][1]
    model = {
        "format": "standardized-logistic-v1",
        "features": list(FEATURES),
        "mean": scaler.mean_.tolist(),
        "scale": scaler.scale_.tolist(),
        "coefficients": classifier.coef_[0].tolist(),
        "intercept": float(classifier.intercept_[0]),
        "C": best[2],
        "sklearn_version": sklearn.__version__,
        "train_sha256": digest(train),
        "validation_sha256": digest(validation),
        "probability_status": "uncalibrated synthetic estimate; not validated for production",
    }
    return pipeline, model, candidates


def score(model, features):
    if model["format"] != "standardized-logistic-v1" or model["features"] != list(FEATURES):
        raise ValueError("unsupported model contract")
    if set(features) != set(FEATURES):
        raise ValueError("feature contract mismatch")
    if any(
        isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value)
        for value in features.values()
    ):
        raise ValueError("invalid scoring input")
    if (
        features["order_quantity"] <= 0
        or features["order_quantity"] % 1
        or not 0 < features["recent_yield"] <= 1
        or features["capacity_load_ratio"] < 0
        or features["allocation_utilization_ratio"] < 0
        or not 0 <= features["pickup_forecast_gap_ratio"] <= 1
        or features["design_changes_30d"] < 0
        or features["design_changes_30d"] % 1
    ):
        raise ValueError("invalid business feature")
    arrays = [model[key] for key in ("mean", "scale", "coefficients")]
    if any(len(values) != len(FEATURES) for values in arrays):
        raise ValueError("invalid model dimensions")
    if not all(math.isfinite(value) for values in arrays for value in values):
        raise ValueError("non-finite model parameter")
    logit = model["intercept"]
    if not math.isfinite(logit):
        raise ValueError("non-finite intercept")
    for index, name in enumerate(FEATURES):
        value, scale = features[name], model["scale"][index]
        if not math.isfinite(value) or scale <= 0:
            raise ValueError("invalid scoring input")
        logit += (value - model["mean"][index]) / scale * model["coefficients"][index]
    if not math.isfinite(logit):
        raise ValueError("scoring arithmetic overflow")
    if logit >= 0:
        return 1 / (1 + math.exp(-logit))
    exponent = math.exp(logit)
    return exponent / (1 + exponent)


def metrics(rows, scores, fraction):
    from sklearn.metrics import average_precision_score, roc_auc_score

    if not rows or not 0 < fraction <= 1 or len(rows) != len(scores):
        raise ValueError("invalid alert budget or scores")
    keys = [(row["entity_id"], row["prediction_at"]) for row in rows]
    if len(set(keys)) != len(keys) or not all(math.isfinite(value) for value in scores):
        raise ValueError("duplicate predictions or invalid scores")
    groups = defaultdict(list)
    for row, value in zip(rows, scores, strict=True):
        if row.get("label") not in (0, 1, None):
            raise ValueError("invalid label")
        groups[row["prediction_at"]].append((value, row["entity_id"], row.get("label")))
    alerts = []
    for values in groups.values():
        alerts.extend(
            sorted(values, key=lambda row: (-row[0], row[1]))[: math.ceil(len(values) * fraction)]
        )
    observed_alerts = [row for row in alerts if row[2] is not None]
    unknown_alerts = len(alerts) - len(observed_alerts)
    tp = sum(row[2] for row in observed_alerts)
    labeled = [
        (row["label"], value)
        for row, value in zip(rows, scores, strict=True)
        if row.get("label") is not None
    ]
    labels = [row[0] for row in labeled]
    labeled_scores = [row[1] for row in labeled]
    positives = sum(labels)
    return {
        "orders": len(rows),
        "labeled_orders": len(labeled),
        "unlabeled_orders": len(rows) - len(labeled),
        "late_orders": positives,
        "alerts": len(alerts),
        "labeled_alerts": len(observed_alerts),
        "unlabeled_alerts": unknown_alerts,
        "true_positives": tp,
        "false_positives": len(observed_alerts) - tp,
        "false_negatives": positives - tp,
        "precision_on_labeled_alerts": tp / len(observed_alerts) if observed_alerts else None,
        "precision_bounds_all_alerts": [tp / len(alerts), (tp + unknown_alerts) / len(alerts)],
        "recall_at_budget": tp / positives if positives else None,
        "average_precision": float(average_precision_score(labels, labeled_scores))
        if positives
        else None,
        "roc_auc": float(roc_auc_score(labels, labeled_scores)) if len(set(labels)) == 2 else None,
    }


def evaluate(pipeline, model, splits, fraction, prediction_rows=None):
    rows = splits["test"] if prediction_rows is None else prediction_rows
    truth = {(row["entity_id"], row["prediction_at"]): row for row in splits["test"]}
    available = {(row["entity_id"], row["prediction_at"]) for row in rows}
    if not truth.keys() <= available:
        raise ValueError("scoring pool omits labeled test orders")
    annotated = []
    for row in rows:
        matched = truth.get((row["entity_id"], row["prediction_at"]))
        if matched is not None and row["features"] != matched["features"]:
            raise ValueError("scoring features differ from historical snapshot")
        annotated.append({**row, "label": matched["label"] if matched is not None else None})
    probabilities = [score(model, row["features"]) for row in rows]
    reference = pipeline.predict_proba(matrix(rows))[:, 1]
    parity = max(abs(left - right) for left, right in zip(probabilities, reference, strict=True))
    if parity > 1e-10:
        raise ValueError("exported scorer disagrees with training pipeline")
    baseline = [rule_score(row["features"]) for row in rows]
    prevalence = sum(row["label"] for row in splits["train"]) / len(splits["train"])
    model_metrics = metrics(annotated, probabilities, fraction)
    labeled = [
        (row, value)
        for row, value in zip(annotated, probabilities, strict=True)
        if row["label"] is not None
    ]
    model_metrics["brier_score"] = sum((value - row["label"]) ** 2 for row, value in labeled) / len(
        labeled
    )
    constant_brier = sum((prevalence - row["label"]) ** 2 for row, _ in labeled) / len(labeled)
    return {
        "budget": f"Top ceil({fraction:.0%} of eligible orders) per weekly prediction date",
        "rule_baseline": metrics(annotated, baseline, fraction),
        "logistic_model": model_metrics,
        "train_prevalence_constant_brier": constant_brier,
        "export_max_abs_error": float(parity),
        "label_policy": "Select alerts from all point-in-time eligible orders before joining matured outcomes; unknown alerts stay in the budget and are reported separately",
        "limits": "Synthetic holdout, one fixed seed; no real accuracy, calibrated probability, intervention benefit or lead-time improvement claim",
    }
