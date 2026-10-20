import math
from collections import Counter


def session_metrics(workflow, actor):
    jobs = [workflow._job(actor, job_id) for job_id in workflow.store.job_ids(actor)]
    counts = Counter(row["status"] for row in jobs)
    calls, events = [], 0
    for row in jobs:
        trace = workflow.trace(actor, row["job_id"])
        events += len(trace)
        calls.extend(event["body"] for event in trace if event["event"] == "model.call")
    real = [row for row in calls if row.get("simulated") is False]
    mocked = [row for row in calls if row.get("simulated") is True]
    durations = sorted(row["wall_ms"] for row in real if type(row.get("wall_ms")) in {float, int})
    known_tokens = bool(real) and all(type(row.get("eval_count")) is int for row in real)
    return {
        "scope": "Local session process and persisted workflow events; not cloud telemetry",
        "jobs": len(jobs),
        "job_states": dict(counts),
        "trace_events": events,
        "queued_jobs": counts["queued"],
        "running_jobs": counts["running"],
        "failed_jobs": counts["failed"],
        "real_model_calls": len(real),
        "mock_response_events": len(mocked),
        "model_error_count": sum(row.get("status") != "ok" for row in real),
        "inference_call_p95_ms": durations[math.ceil(len(durations) * 0.95) - 1]
        if durations
        else None,
        "completion_tokens": sum(row["eval_count"] for row in real) if known_tokens else None,
        "billed_cost": None,
        "cost_status": "not_measured",
        "live_model_enabled": any(row.get("provider") in {"aws_bedrock", "ollama_local"} and row.get("simulated") is False for row in workflow.runtime_identity().values()),
        "customer_send_enabled": False,
    }
