import json
import os
from pathlib import Path

import streamlit as st

from agent.service import Service
from config.contracts import Scope
from evaluation.eval_pipeline import evaluate
from evaluation.gates import release_gates
from evaluation.judge import review_labels
from mock_data.generator import generate

st.set_page_config(page_title="Quote & Capacity Lab", page_icon="◈", layout="wide")
st.html("""
<style>
.stApp { background: radial-gradient(ellipse at 15% 5%, #e2eafa 0%, transparent 45%), radial-gradient(ellipse at 90% 80%, #e6f2ed 0%, transparent 45%), #f5f6fa; color: #202b40; }
[data-testid="stHeader"] { background: transparent; }
[data-testid="stVerticalBlockBorderWrapper"] > div { background: rgba(255,255,255,.66); border: 1px solid rgba(255,255,255,.95); border-radius: 22px; box-shadow: 0 12px 40px rgba(51,68,100,.05); padding: 14px; backdrop-filter: blur(18px); }
[data-testid="stMetric"] { background: rgba(255,255,255,.7); border-radius: 18px; padding: 20px; }
h1 { letter-spacing: -.04em; }
.stButton button { border-radius: 14px; }
</style>
""")
st.title("Quote & Capacity Lab")
st.caption("A customer request. Checked facts. A reviewable proposal.")
scope = Scope(customer_id="CUSTOMER-A", project_id="PROJECT-A")
root = Path(os.getenv("AGENT_STUDIO_ROOT", "runtime/studio"))
initial = not (root / "source/manifest.json").exists()
if initial:
    generate(root / "source")
service = Service(root)
st.info(
    "Real LLM mode · Local semantic retrieval · Source-bound checks"
    if service.live_graph
    else "Offline fallback · Real LangGraph execution · No model calls"
)
if service.fallback_reason:
    st.caption(service.fallback_reason)
if initial:
    service.ingest_all()
    service.memory.store_preference(scope, "shipping_term", "FOB Port Alpha", "MAIL-001:v1", True)

scenario_tab, eval_tab, trace_tab = st.tabs(["Customer Scenario", "Evaluation", "Workflow Trace"])
with scenario_tab:
    with st.container(border=True):
        st.subheader("A lower price. A tighter deadline.")
        st.write(
            "The customer asks for 5% off. ECN v2 requires 28 days. PLANT-A has only 2,000 units available; PLANT-B has 40,000."
        )
        left, middle, right = st.columns(3)
        quantity = left.number_input(
            "Order quantity", min_value=1, max_value=1000000, value=12000, step=1000
        )
        days = middle.number_input("Requested delivery days", min_value=1, max_value=365, value=14)
        factory = right.selectbox("Preferred factory", ["PLANT-A", "PLANT-B"])
        if st.button("Prepare proposal", type="primary"):
            request = {
                "prompt": "Prepare a discounted quote",
                "quantity": int(quantity),
                "requested_days": int(days),
                "preferred_factory": factory,
            }
            st.session_state["proposal"] = service.run("demo-manager", scope, request)
            st.session_state["request"] = request
            st.session_state.pop("approval", None)
    if "proposal" in st.session_state:
        artifact = st.session_state["proposal"]["artifact"]
        option = artifact["result"]
        a, b, c = st.columns(3)
        a.metric("Unit price", f"${option['unit_price_cents'] / 100:.2f}")
        b.metric("Minimum delivery", f"{option['lead_days']} days")
        c.metric("Proposed factory", option["factory_id"])
        with st.container(border=True):
            if artifact["status"] == "blocked":
                st.error("Capacity review required. Neither factory can cover this quantity.")
            else:
                st.success("Ready for manager review. No capacity has been reserved.")
            st.write("Required inspection stays included. Future volume remains uncommitted.")
            changed = (quantity, days, factory) != (
                option["quantity"],
                st.session_state["request"]["requested_days"],
                st.session_state["request"]["preferred_factory"],
            )
            if changed:
                st.warning("Inputs changed. Prepare a new proposal before approval.")
            if st.button(
                "Approve internal proposal", disabled=changed or artifact["status"] == "blocked"
            ):
                try:
                    service.approve("demo-manager", scope, artifact, st.session_state["request"])
                    st.session_state["approval"] = (
                        "Approved for internal review only. Nothing was sent to the customer."
                    )
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
            if "approval" in st.session_state:
                st.success(st.session_state["approval"])
            with st.expander("Supporting evidence"):
                for row in artifact["evidence"]:
                    meta = row["metadata"]
                    st.markdown(f"**{meta['document_id']} · Version {meta['version']}**")
                    st.text(row["text"])

with eval_tab:
    st.subheader("Can the proposal pass the business checks?")
    st.caption(
        "5 authored fixtures + 18 parameterized cases. Review and release status require recorded evidence."
    )
    if st.button("Run evaluation"):
        st.session_state["report"] = evaluate(service)
    with st.expander("Qualification checks"):
        if st.button("Review labels with independent judge"):
            review = review_labels(service.root, service.config.judge_model)
            st.write(
                {
                    "review_status": review["review_status"],
                    "mode": review["mode"],
                    "cases": len(review["rows"]),
                }
            )
        if st.button("Check AgentCore local HTTP"):
            from deployment.self_check import local_check

            deployment = local_check(service.root)
            st.write(deployment["checks"])
    saved = root / "evaluation.json"
    report = st.session_state.get("report") or (
        json.loads(saved.read_text()) if saved.exists() else None
    )
    if report:
        a, b, c = st.columns(3)
        a.metric("Cases passed", f"{report['passed']} / {report['cases']}")
        b.metric(
            "Capacity overcommitment", f"{report['metrics']['capacity_overcommitment_rate']:.0%}"
        )
        c.metric(
            "Delivery constraints met", f"{report['metrics']['delivery_constraint_pass_rate']:.0%}"
        )
        st.dataframe(
            [
                {
                    "Case": row["case_id"],
                    "Result": "Pass" if row["passed"] else "Fail",
                    "Failed checks": ", ".join(row["failure_categories"]) or "None",
                }
                for row in report["rows"]
            ],
            hide_index=True,
            width="stretch",
        )
        memory_metrics = report.get("memory", {}).get("metrics", {})
        if memory_metrics:
            st.subheader("Memory Eval")
            st.dataframe(
                [
                    {"Metric": name.replace("_", " ").title(), "Pass rate": f"{value:.0%}"}
                    for name, value in memory_metrics.items()
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "Synthetic lifecycle tests. Abstention is measured only on unanswerable cases; answerable queries are checked separately."
            )
        gates = release_gates(report, service.root)
        report["release"] = gates
        if gates["local_acceptance_passed"]:
            st.success("Local Acceptance Gate passed: business contracts and Memory Eval.")
        if gates["production_approved"]:
            st.success(
                "Production Gate passed — local release validation."
                if gates["qualification_scope"] == "local_release"
                else "Production Gate passed: cloud qualification evidence is current."
            )
            if gates["qualification_scope"] == "local_release":
                st.caption(
                    "Scope: real-model evaluation, independent model review, local AgentCore HTTP and static Dockerfile checks. AWS rollout and container execution are not certified."
                )
        else:
            st.warning(
                "Production Gate pending: "
                + ", ".join(name.replace("_", " ") for name in gates["blockers"])
            )
        with st.expander("Production Gate evidence"):
            st.dataframe(
                [
                    {
                        "Requirement": name.replace("_", " ").title(),
                        "Status": "Passed" if gates[name] else "Pending",
                    }
                    for name in [
                        "local_contracts_pass",
                        "independent_labels_reviewed",
                        "real_llm_evaluated",
                        "deployment_checks_pass",
                    ]
                ],
                hide_index=True,
                width="stretch",
            )
        if report.get("runtime_mode") == "llm":
            with st.expander("LangSmith runs and usage"):
                st.write(
                    {
                        "Model calls": report.get("external_api_calls"),
                        "Tokens": report.get("usage", {}),
                        "Run IDs": sum(bool(row.get("case_trace_id")) for row in report["rows"]),
                    }
                )
                st.dataframe(
                    [
                        {
                            "Case": row["case_id"],
                            "Run ID": row.get("case_trace_id"),
                            "Mode": row.get("runtime", {}).get("mode", "validation_error"),
                            "Tokens": row.get("runtime", {})
                            .get("usage", {})
                            .get("total_tokens", 0),
                            "Elapsed ms": row["elapsed_ms"],
                        }
                        for row in report["rows"]
                    ],
                    hide_index=True,
                    width="stretch",
                )
        st.download_button(
            "Download evaluation report",
            json.dumps(report, indent=2),
            "evaluation.json",
            "application/json",
        )
    else:
        st.write(
            "Run the suite to check capacity, delivery constraints, quote math, evidence and tool routing."
        )

with trace_tab:
    st.subheader("Workflow event sequence")
    result = st.session_state.get("proposal")
    if result:
        for index, event in enumerate(result["events"], 1):
            with st.container(border=True):
                st.markdown(f"**{index:02d} · {event['step'].replace('_', ' ').title()}**")
                st.write({key: value for key, value in event.items() if key != "step"})
        with st.expander("Agent handoffs"):
            st.json(result["messages"])
    else:
        st.write("Prepare a proposal to inspect the executed steps and handoffs.")
