const paths = {
  grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
  data: "M20 6c0 2-4 3-8 3S4 8 4 6s4-3 8-3 8 1 8 3z M4 6v12c0 2 4 3 8 3s8-1 8-3V6 M4 12c0 2 4 3 8 3s8-1 8-3",
  chart: "M4 20h17 M7 16V9 M12 16V4 M17 16v-5",
  trace: "M6 4v16 M6 7h7l4 4 M6 16h10 M17 8v6 M13 16l3-3 3 3",
  gate: "M4 20V5h16v15 M9 20v-8h6v8 M2 20h20",
  refresh: "M20 10a8 8 0 10-2 8 M20 4v6h-6",
  download: "M12 3v12 M7 10l5 5 5-5 M5 16v5h14v-5",
  arrow: "M7 17L17 7 M7 7h10v10",
  chevron: "M9 5l7 7-7 7",
  clock: "M12 3a9 9 0 100 18 9 9 0 000-18 M12 7v5l3 2",
  check: "M5 12l4 4L19 6",
  info: "M12 3a9 9 0 100 18 9 9 0 000-18 M12 11v6 M12 7v1",
  layers: "M3 8l9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5",
  users:
    "M9 11a4 4 0 100-8 4 4 0 000 8 M2 21v-3c0-3 3-4 7-4s7 1 7 4v3 M17 4c4 0 4 6 0 6 M18 14c3 0 4 2 4 5",
  calc: "M5 2h14v20H5z M8 6h8 M8 11h1 M15 11h1 M8 15h1 M15 15h1 M8 19h1 M15 19h1",
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.info}"/></svg>`;
const esc = (value) =>
  String(value ?? "—").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
const pct = (v) => (v == null ? "—" : `${(Number(v) * 100).toFixed(1)}%`);
const decimal = (v) => (v == null ? "—" : Number(v).toFixed(3));
const dollars = (v) =>
  v == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 2,
      }).format(v / 100);
const labels = {
  "draft.queued": "Draft queued",
  "evidence.retrieve": "Evidence retrieved",
  "engineering.complete": "Engineering analysis",
  "business.complete": "Pricing options",
  "draft.validated": "Draft checked",
  "manager.follow_up": "Manager follow-up",
  "manager.approved_internal": "Internal approval",
  "manager.revision_invalidates_approval": "Quantity changed",
  draft_generation_is_queued: "Draft generation uses the queue",
  current_etl_and_four_rag_conditions_used:
    "Correct order and complete source conditions",
  requested_five_percent_below_demo_margin_floor:
    "Requested discount is checked against policy",
  counteroffer_1445_cents_passes: "Counteroffer clears the margin floor",
  approval_bound_to_payload: "Approval binds the exact draft",
  revision_invalidates_old_approval:
    "Quantity changes invalidate prior approval",
  hypothetical_volume_is_not_customer_commitment:
    "What-if volume stays uncommitted",
  unit_cost_does_not_fall_without_approved_evidence:
    "No unsupported unit-cost reduction",
  revised_cost_and_counteroffer_recomputed: "Quote totals recalculate exactly",
  shared_capacity_shortfall_blocks_approval:
    "Capacity shortfalls block approval",
  stale_and_infeasible_approvals_rejected:
    "Stale and infeasible approvals are rejected",
  what_if_does_not_modify_etl: "What-if scenarios do not overwrite ETL",
  same_model_reused_without_retraining:
    "Frozen model reused without retraining",
  no_paid_calls_or_customer_send: "Local execution; no customer dispatch",
  input_orders_accounted_for: "All input orders are accounted for",
  split_rows_accounted_for: "Retained and excluded rows reconcile",
  features_available_at_prediction: "Only evidence available at prediction",
  historical_yield_only: "Yield uses historical measurements",
  feature_allowlist: "Only approved features enter the model",
  unique_orders_across_splits: "No order crosses data partitions",
  labels_available_before_fitting_cutoffs:
    "Labels were available before fitting",
  chronological_prediction_windows: "Train and test windows stay chronological",
};
const title = (v) =>
  labels[v] ||
  String(v)
    .replace(/[._-]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .replace(/\b(Etl|Rag|Ml|Api|Sql|Llm|Sdk)\b/g, (c) => c.toUpperCase());
const badge = (text, tone = "") =>
  `<span class="badge ${tone}">${esc(text)}</span>`;
const sections = [
  ["overview", "Overview", "grid"],
  ["agents", "Agent Eval", "shield"],
  ["data", "Data & RAG", "data"],
  ["risk", "Risk Model", "chart"],
  ["traces", "Run Traces", "trace"],
  ["gates", "Release Gates", "gate"],
];
const state = {
  data: null,
  page: "overview",
  draft: "initial",
  details: [],
};
const main = document.querySelector("#main");
const nav = document.querySelector("#navigation");
const e = () => state.data.evidence;
const flow = () => e().agents;
function detailButton(label, value, kind = "Evidence detail") {
  const id = state.details.push({ label, value, kind }) - 1;
  return `<button class="text-button" data-detail="${id}">${esc(label)} ${icon("arrow")}</button>`;
}
function rowDetail(label, value) {
  return state.details.push({ label, value, kind: "Evaluation evidence" }) - 1;
}
function openDetail(id) {
  const item = state.details[Number(id)];
  if (!item) return;
  const value = item.value;
  document.querySelector("#detail-title").textContent = item.label;
  document.querySelector("#detail-eyebrow").textContent =
    item.kind.toUpperCase();
  const target = document.querySelector("#detail-content");
  target.replaceChildren();
  const intro = document.createElement("div");
  if (value && value.case_id && value.observed) {
    intro.innerHTML = `<div class="detail-result">${badge(value.passed ? "Guard verified" : "Evaluation failed", value.passed ? "" : "red")}${badge(value.category, "blue")}</div><p class="detail-lead">${esc(value.title)}. The expected result is to reject the unsafe action.</p><div class="compact-note"><strong>Observed reason</strong><br>${esc(value.reason)}</div><div class="section-label">What the evaluator verified</div><div class="checklist">${Object.entries(
      value.checks || {},
    )
      .map(
        ([key, passed]) =>
          `<div class="check-row"><span class="check-icon ${passed ? "" : "fail"}">${passed ? "✓" : "×"}</span><span class="check-label">${esc(title(key))}</span></div>`,
      )
      .join(
        "",
      )}</div><div class="mini-stats"><span>Recorded draft state</span><strong>${esc(value.draft_state || "No draft created")}</strong></div><div class="mini-stats"><span>Local experiment duration</span><strong>${value.elapsed_ms == null ? "—" : `${Number(value.elapsed_ms).toFixed(1)} ms`}</strong></div><div class="section-label">Recorded execution path</div><div class="pills">${(value.trace || []).map((row) => badge(title(row.event), "muted")).join("") || badge("Denied before a draft was created", "muted")}</div>`;
  } else if (value && value.case_id) {
    intro.innerHTML = `<div class="detail-result">${badge(value.passed ? "Passed" : "Review result", value.passed ? "" : "amber")}</div><p class="detail-lead">${esc(title(value.case_id))}</p><dl class="context-list">${contextRow("Recall @ k", pct(value.recall_at_k))}${contextRow("Precision @ k", pct(value.precision_at_k))}${contextRow("Condition coverage", pct(value.condition_coverage))}</dl>`;
  } else if (value && value.draft) {
    const draft = value.draft;
    intro.innerHTML = `<div class="detail-result">${badge(title(value.status), "amber")}${badge(`Revision ${value.revision}`, "blue")}</div><p class="detail-lead">A versioned internal proposal. Approval status and capacity constraints apply separately from pricing arithmetic.</p><div class="draft-summary"><div><label>Scenario quantity</label><strong>${num(draft.quantity)}</strong></div><div><label>Unit cost</label><strong>${dollars(draft.engineering.costing.unit_cost_cents)}</strong></div><div><label>Capacity gap</label><strong>${num(draft.engineering.risk.capacity_shortfall_units)}</strong></div></div><p class="legend-note">The complete numeric proposal, source fingerprints and approval binding are available below.</p>`;
  } else if (value && value.event) {
    intro.innerHTML = `<div class="detail-result">${badge(`Step ${value.seq}`, "blue")}${badge("Recorded event", "muted")}</div><p class="detail-lead">${esc(traceSummary(value))}</p>${eventDetail(value)}`;
  } else {
    intro.innerHTML =
      '<p class="detail-lead">Recorded input, checks and result from this local evaluation. This evidence is scoped to synthetic local runs.</p>';
  }
  target.append(intro);
  const details = document.createElement("details");
  details.className = "raw-evidence";
  details.open = false;
  const label = document.createElement("summary");
  label.textContent = "Technical evidence · JSON";
  const pre = document.createElement("pre");
  pre.className = "detail-json";
  pre.textContent = JSON.stringify(value, null, 2);
  details.append(label, pre);
  target.append(details);
  const dialog = document.querySelector("#detail-dialog");
  if (!dialog.open) dialog.showModal();
}
function metric(label, value, unit, foot, name) {
  return `<article class="metric-card"><div class="metric-label">${esc(label)}</div><span class="metric-icon">${icon(name)}</span><div class="metric-value">${esc(value)}<small>${esc(unit)}</small></div><div class="metric-foot"><span class="tiny-dot"></span>${esc(foot)}</div></article>`;
}
function heading(eyebrow, name, description) {
  const fresh = state.data.freshness.current;
  const stamp = state.data.verified_at_utc
    ? new Date(state.data.verified_at_utc).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      })
    : "Not recorded";
  return `<div class="page-heading"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${esc(name)}</h1><p>${esc(description)}</p></div><div class="page-status"><div class="status-line ${fresh && e().passed ? "" : "warning"}"><i class="status-dot"></i>${fresh && e().passed ? "Local checks passed" : "Review evidence status"}</div><small>${esc(stamp)} UTC</small></div></div>${fresh ? "" : `<div class="notice">${icon("info")}<span>Source files have changed since this verification. Rerun the evaluation before trusting its gate.</span>${detailButton("Inspect changes", state.data.freshness)}</div>`}`;
}
function checklist(checks, limit) {
  return `<div class="checklist">${Object.entries(checks || {})
    .slice(0, limit)
    .map(
      ([key, passed]) =>
        `<button class="check-row row-button" data-detail="${rowDetail(title(key), { check: key, passed })}"><span class="check-icon ${passed ? "" : "fail"}">${passed ? "✓" : "×"}</span><span class="check-label">${esc(title(key))}</span><span class="check-caption">${passed ? "Passed" : "Failed"}</span></button>`,
    )
    .join("")}</div>`;
}
function absent(name) {
  return `<section class="panel full-panel"><h2>${esc(name)} has not been run.</h2><p class="detail-lead">Run the full local verification to populate this section. Missing evidence is not a pass.</p><code>.venv/bin/python -m scripts.verify --agents</code></section>`;
}
function overview() {
  const v = e(),
    a = flow(),
    faults = v.agent_eval;
  let html = heading(
    "OBSERVE. EVALUATE. UNDERSTAND.",
    "Confidence, with evidence.",
    "A clear view of what passed, what was blocked, and why.",
  );
  html += `<div class="metrics">${metric("Verification tests", num(v.unit_tests?.count), "", `${num(v.unit_tests?.skipped)} skipped · recorded test run`, "check")}${metric("Workflow checks", a ? Object.values(a.checks).filter(Boolean).length : "—", a ? `/ ${Object.keys(a.checks).length}` : "", "Discount + quantity revision", "layers")}${metric("Fault experiments", faults ? faults.passed_count : "—", faults ? `/ ${faults.case_count}` : "", "Unsafe actions rejected as expected", "shield")}${metric("External API calls", a ? a.initial.draft.external_api_calls + a.revised.draft.external_api_calls : "—", "", "Recorded two-draft workflow", "chart")}</div>`;
  if (!a) return html + absent("Multi-Agent evaluation");
  const job = a[state.draft],
    draft = job.draft,
    requested = draft.business.options.find(
      (x) => x.option_id === "customer_request",
    ),
    counter = draft.business.options.find(
      (x) => x.option_id === "counteroffer",
    ),
    risk = draft.engineering.risk;
  html += `<div class="grid"><section class="panel"><span class="eyebrow">THE SCENARIO</span>${badge("Customer A · Project A", "blue")}<h2 class="scenario-heading">A discount request.<br>Two accountable drafts.</h2><p class="scenario-description">The customer asks for 5% off. Business and engineering review the same evidence, then recalculate when the manager changes volume.</p><div class="scope-line">${icon("layers")}<b>${esc(draft.scope.entity_id)}</b><span>·</span> ETL v${draft.facts.business_version}<span>·</span> Design ${esc(draft.facts.design_version)}</div><div class="segmented" aria-label="Draft selection"><button data-draft="initial" class="${state.draft === "initial" ? "selected" : ""}">Original · 12,000</button><button data-draft="revised" class="${state.draft === "revised" ? "selected" : ""}">Revised · 18,000</button></div><div class="draft-summary"><div><label>Scenario volume</label><strong>${num(draft.quantity)}</strong> <small>units</small></div><div><label>Total cost</label><strong>${dollars(draft.engineering.costing.total_cost_cents)}</strong></div><div><label>Counteroffer total</label><strong>${dollars(counter.revenue_cents)}</strong></div></div><div class="decision-note">${icon("info")}<span>${state.draft === "initial" ? "Historical draft: internally approved, then superseded by the quantity revision. Its old approval is no longer valid." : "What-if volume is not a signed commitment. Published ETL quantity remains 12,000; the new draft requires capacity review."}</span></div></section><section class="panel"><div class="panel-title"><div><h2>Price & delivery boundaries</h2><p class="panel-subtitle">Independent checks before internal approval</p></div>${icon("shield")}</div><div class="quote-tile"><div><span class="quote-label">Customer request</span><strong>${dollars(requested.unit_price_cents)}</strong><small>${(requested.margin_bps / 100).toFixed(2)}% gross margin · 10% demo floor</small></div>${badge(requested.margin_allowed ? "Within floor" : "Below floor", requested.margin_allowed ? "" : "amber")}</div><div class="quote-tile preferred"><div><span class="quote-label">Policy-constrained counteroffer</span><strong>${dollars(counter.unit_price_cents)}</strong><small>${(counter.margin_bps / 100).toFixed(2)}% gross margin · per unit</small></div>${badge("Pricing passes", "blue")}</div><div class="mini-stats"><span>Capacity shortfall</span><strong>${num(risk.capacity_shortfall_units)} units</strong></div><div class="mini-stats"><span>Internal approval</span>${badge(risk.requires_capacity_review ? "Capacity review required" : "Historical approval superseded", "amber")}</div><p class="legend-note">10% is an invented demo policy. These are internal options, not an optimized or customer-approved quote.</p><div class="spaced">${detailButton("Inspect this draft", job)}</div></section></div><section class="panel section-space"><div class="panel-title"><div><h2>One trace, across the workflow.</h2><p class="panel-subtitle">Shared snapshot → structured handoff → validated internal draft</p></div><a class="text-button" href="#traces">Explore trace ${icon("arrow")}</a></div><div class="pipeline">${[
    ["data", "Scoped evidence"],
    ["calc", "Engineering"],
    ["users", "Business"],
    ["shield", "Validation"],
    ["gate", "Manager review"],
  ]
    .map(([i, label]) => `<div class="pipeline-step">${icon(i)}${label}</div>`)
    .join(
      "",
    )}</div></section><div class="grid"><section class="panel"><div class="panel-title"><h2>Checks that protect the decision</h2>${badge("Local fixture", "muted")}</div>${disclosure("Workflow assertions", checklist(a.checks), checkCount(a.checks))}<div class="spaced"><a class="text-button" href="#agents">Explore agent evaluation ${icon("arrow")}</a></div></section><section class="panel"><div class="panel-title"><h2>Know the limits</h2>${icon("info")}</div><div class="compact-note">${risk.outside_training_range.length ? "The revised 18,000-unit quantity exceeds the model training range. Its score is advisory; deterministic capacity arithmetic blocks approval." : "The risk model is synthetic and unpromoted. A score is an input to review, not a delivery promise."}</div><div class="check-row"><span class="check-label">Evidence generation</span>${badge("Deterministic", "blue")}</div><div class="check-row"><span class="check-label">Customer dispatch</span>${badge("Disabled", "muted")}</div><div class="check-row"><span class="check-label">Production model promotion</span>${badge("On hold", "amber")}</div><div class="spaced"><a href="#gates" class="text-button">Inspect release gates ${icon("arrow")}</a></div></section></div>`;
  return html;
}
function disclosure(label, content, meta = "") {
  return `<details class="disclosure"><summary><span>${esc(label)}</span><span class="disclosure-meta">${esc(meta)}${icon("chevron")}</span></summary><div class="disclosure-body">${content}</div></details>`;
}
function checkCount(checks) {
  const values = Object.values(checks || {});
  return `${values.filter((value) => value === true).length} / ${values.length}`;
}
function contextRow(label, value) {
  return `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
}
function agents() {
  const a = flow(),
    f = e().agent_eval;
  let html = heading(
    "AGENT EVALUATION",
    "Does the decision hold up?",
    "Evidence, pricing and manager changes — checked before approval.",
  );
  if (!f) return html + absent("Controlled fault evaluation");
  html += `<div class="metrics metrics-three">${metric("Workflow checks", checkCount(a?.checks), "", "Quote and quantity revision", "check")}${metric("Unsafe actions blocked", `${f.passed_count} / ${f.case_count}`, "", "Expected rejection + matching reason", "shield")}${metric("Feedback checks", checkCount(f.manager_feedback?.checks), "", "Rejection, revision and review", "users")}</div><section class="panel full-panel"><div class="panel-title"><div><h2>What we test</h2><p class="panel-subtitle">Open a category to inspect its cases.</p></div>${badge(f.passed ? "Checks passed" : "Review failures", f.passed ? "" : "red")}</div><div class="eval-groups">${[
    ["Evidence", "Missing conditions and stale source data"],
    ["Pricing", "Costs and quote totals must match"],
    ["Recalculation", "Order changes and shared capacity"],
    ["Access", "Customer scope and revoked permissions"],
    ["Approval", "Only the checked draft can be approved"],
  ]
    .map(([category, description]) => {
      const rows = f.cases.filter((row) => row.category === category);
      return `<details class="eval-group"><summary><span><strong>${esc(category)}</strong><small>${esc(description)}</small></span>${badge(`${rows.filter((row) => row.passed).length} / ${rows.length}`, rows.every((row) => row.passed) ? "" : "red")}${icon("chevron")}</summary><div class="eval-group-body">${rows.map((row) => `<button class="case-button" data-detail="${rowDetail(row.title, row)}"><span>${esc(row.title)}</span>${badge(row.passed ? "Blocked as expected" : "Unexpected result", row.passed ? "" : "red")}${icon("chevron")}</button>`).join("")}</div></details>`;
    })
    .join("")}</div></section>`;
  html += managerFeedbackPanel(f.manager_feedback);
  html += `<section class="panel full-panel"><div class="panel-title"><h2>Validation details</h2>${badge("Offline", "muted")}</div>${disclosure("Workflow assertions", checklist(a?.checks), checkCount(a?.checks))}${modelContractsPanel(e().model_contracts)}<p class="legend-note">Synthetic local checks. Real model quality and production performance have not been measured.</p></section>`;
  return html;
}
function dataPage() {
  const v = e(),
    r = v.rag_evaluation,
    retrieval = r?.retrieval;
  const faults = v.fault_experiments?.experiments || [],
    loads = v.load_evaluation?.scenarios || [];
  let html = heading(
    "DATA & RETRIEVAL",
    "Can we trust the inputs?",
    "Check completeness, recovery and the evidence each customer can retrieve.",
  );
  html += `<div class="metrics metrics-three">${metric("ETL recovery", `${faults.filter((row) => row.passed).length} / ${faults.length}`, "", "Replay and crash recovery", "trace")}${metric("Load checks", `${loads.filter((row) => row.passed).length} / ${loads.length}`, "", "Independent reconciliation", "data")}${metric("Retrieval cases", retrieval ? `${retrieval.cases.filter((row) => row.passed).length} / ${retrieval.cases.length}` : "—", "", "Sources, versions and permissions", "shield")}</div>`;
  const missing = loads.reduce(
    (sum, row) => sum + row.event_reconciliation.missing_events,
    0,
  );
  html += `<section class="panel full-panel"><div class="panel-title"><h2>Data reaches the right decision</h2>${badge("Local fixtures", "muted")}</div><dl class="context-list">${contextRow("Completeness", `${loads.length ? `${num(missing)} missing events across ${loads.length} load scenarios` : "Not measured"}`)}${contextRow("Recovery", `${faults.filter((row) => row.passed).length} of ${faults.length} fault experiments passed`)}${contextRow("RAG boundaries", `${r?.lifecycle?.length ?? 0} update, deletion and permission experiments`)}</dl><p class="legend-note">These are local fixture results, not production capacity or general answer-quality scores.</p></section>`;
  const etl = `<div class="checklist">${faults.map((row) => `<button class="check-row row-button" data-detail="${rowDetail(row.experiment, row)}"><span class="check-icon ${row.passed ? "" : "fail"}">${row.passed ? "✓" : "×"}</span><span class="check-label">${esc(row.experiment)}</span>${icon("chevron")}</button>`).join("")}</div>`;
  const load = loads
    .map(
      (row) =>
        `<button class="check-row row-button" data-detail="${rowDetail(`${title(row.scenario)} load scenario`, row)}"><span class="check-icon ${row.passed ? "" : "fail"}">${row.passed ? "✓" : "×"}</span><span class="check-label">${esc(title(row.scenario))} · ${num(row.input_changes)} changes</span><span class="check-caption">${num(row.event_reconciliation.missing_events)} missing</span></button>`,
    )
    .join("");
  let retrievalTable =
    '<p class="legend-note">Retrieval evidence is unavailable.</p>';
  if (retrieval)
    retrievalTable = `<div class="table-wrap"><table><thead><tr><th>Case</th><th>Recall @ k</th><th>Precision @ k</th><th>Conditions</th><th>Result</th></tr></thead><tbody>${retrieval.cases.map((row) => `<tr tabindex="0" data-detail="${rowDetail(row.case_id, row)}"><td class="case-name">${esc(title(row.case_id))}</td><td>${pct(row.recall_at_k)}</td><td>${pct(row.precision_at_k)}</td><td>${pct(row.condition_coverage)}</td><td>${badge(row.passed ? "Passed" : "Failed", row.passed ? "" : "red")}</td></tr>`).join("")}</tbody></table></div><p class="legend-note">Fixed-k document retrieval and annotated condition coverage. Unlabeled metrics display “—”.</p>`;
  return (
    html +
    `<section class="panel full-panel"><div class="panel-title"><h2>Inspect the tests</h2></div>${disclosure("ETL recovery", etl, `${faults.length} experiments`)}${disclosure("Load reconciliation", load, `${loads.length} scenarios`)}${disclosure("Retrieval quality", retrievalTable, `${retrieval?.cases.length ?? 0} cases`)}${disclosure("Document lifecycle", detailButton("Inspect lifecycle evidence", r?.lifecycle || []), `${r?.lifecycle?.length ?? 0} experiments`)}</section>`
  );
}
function riskPage() {
  const r = e().risk_model;
  let html = heading(
    "ML EVALUATION",
    "Does the model beat the baseline?",
    "Compare the same time window and alert budget.",
  );
  if (!r) return html + absent("Risk Model");
  const m = r.evaluation.logistic_model,
    b = r.evaluation.rule_baseline;
  const uplift = m.recall_at_budget > b.recall_at_budget;
  html += `<div class="notice">${icon("info")}<span>${uplift ? "Observed recall improved in this synthetic holdout. Production qualification is still separate." : "Keep the rules baseline. The model did not find more delays at the same alert budget."}</span></div><div class="metrics metrics-three">${metric("Scored orders", m.orders, "", "Eligible holdout orders", "data")}${metric("Known outcomes", m.labeled_orders, "", `${num(m.unlabeled_orders)} still pending`, "clock")}${metric("Alert budget", m.alerts, "", "Same budget for rules and model", "shield")}</div><section class="panel full-panel"><div class="panel-title"><div><h2>Delivery delays found</h2><p class="panel-subtitle">Recall among orders with confirmed outcomes</p></div>${badge("Synthetic holdout", "muted")}</div><div class="risk-comparison">${[
    [b, "Rules baseline", ""],
    [m, "Logistic model", "model"],
  ]
    .map(
      ([value, name, klass]) =>
        `<article class="risk-block ${klass}"><h3>${name}</h3><div class="big-number">${(value.recall_at_budget * 100).toFixed(1)}<small>%</small></div><div class="bar-track"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, value.recall_at_budget * 100))}%"></div></div><p>${value.true_positives} known delays found · ${value.alerts} alerts</p></article>`,
    )
    .join(
      "",
    )}</div><p class="legend-note">Pending outcomes are not counted as on-time deliveries.</p></section>`;
  const ranking = `<div class="table-wrap"><table><thead><tr><th>Metric</th><th>Rules</th><th>Model</th></tr></thead><tbody>${[
    [
      "Average precision",
      decimal(b.average_precision),
      decimal(m.average_precision),
    ],
    ["ROC-AUC", decimal(b.roc_auc), decimal(m.roc_auc)],
    [
      "Precision on labeled alerts",
      pct(b.precision_on_labeled_alerts),
      pct(m.precision_on_labeled_alerts),
    ],
    [
      "All-alert precision bounds",
      b.precision_bounds_all_alerts.map(pct).join(" – "),
      m.precision_bounds_all_alerts.map(pct).join(" – "),
    ],
    ["Alerts awaiting labels", b.unlabeled_alerts, m.unlabeled_alerts],
  ]
    .map(
      (row) =>
        `<tr>${row.map((value) => `<td>${esc(value)}</td>`).join("")}</tr>`,
    )
    .join(
      "",
    )}</tbody></table></div><p class="legend-note">Bounds reflect unknown labels, not confidence intervals.</p>${detailButton("Inspect evaluation report", r.evaluation)}`;
  return (
    html +
    `<section class="panel full-panel"><div class="panel-title"><h2>Evaluation details</h2></div>${disclosure("Ranking and label coverage", ranking)}${disclosure("Time split and leakage checks", `${checklist(r.audit)}${detailButton("Inspect temporal dataset", r.dataset)}`, checkCount(r.audit))}</section>`
  );
}
function tracesPage() {
  const a = flow();
  let html = heading(
    "RUN TRACES",
    "Follow the decision.",
    "One order, its evidence, and each step of the review.",
  );
  if (!a) return html + absent("Agent traces");
  const job = a[state.draft],
    draft = job.draft,
    risk = draft.engineering.risk;
  const rows = a.traces[state.draft] || [];
  const evidence = rows.find((row) => row.event === "evidence.retrieve")?.body;
  const counter = draft.business.options.find(
    (row) => row.option_id === "counteroffer",
  );
  const superseded = rows.some(
    (row) => row.event === "manager.revision_invalidates_approval",
  );
  const status =
    superseded || job.status === "superseded"
      ? "Superseded"
      : job.status === "needs_capacity_review"
        ? "Capacity review needed"
        : title(job.status);
  const summary = `<section class="panel run-summary"><div class="panel-title"><h2>Run summary</h2>${badge(`Revision ${job.revision}`, "blue")}</div><div class="run-scope"><strong>${esc(draft.scope.customer_id.replace("CUSTOMER-", "Customer "))} · ${esc(draft.scope.project_id.replace("PROJECT-", "Project "))}</strong><span>${esc(draft.scope.entity_id)}</span></div><dl class="context-list">${contextRow("Scenario quantity", `${num(draft.quantity)} units`)}${contextRow("Source version", `ETL v${draft.facts.business_version} · Design ${draft.facts.design_version}`)}${contextRow("Evidence", evidence ? `${evidence.chunks.length} passages from ${new Set(evidence.chunks.map((chunk) => chunk.split(":")[0])).size} documents` : "Not recorded")}${contextRow("Counteroffer", counter ? `${dollars(counter.unit_price_cents)} / unit` : "Not recorded")}${contextRow("Capacity gap", `${num(risk.capacity_shortfall_units)} units`)}${contextRow("Review status", status)}</dl><div class="compact-note">${risk.requires_capacity_review ? `This scenario leaves a ${num(risk.capacity_shortfall_units)}-unit capacity gap. Approval stays blocked.` : superseded ? "The original approval was superseded when quantity changed. It cannot be reused." : "This draft remains internal. No customer proposal has been sent."}</div><p class="legend-note">Recorded local workflow · ${num(draft.llm_calls)} real model calls</p>${disclosure(
    "Technical details",
    `<p class="legend-note">Fingerprints bind this run to its inputs. They are version checksums, not business data.</p><dl class="fingerprint-list">${Object.entries(
      draft.input_fingerprints,
    )
      .map(
        ([key, value]) =>
          `<div><dt>${esc(title(key))}</dt><dd><code>${esc(value)}</code></dd></div>`,
      )
      .join("")}</dl>${detailButton("Inspect complete draft", job)}`,
  )}</section>`;
  html += `<div class="grid trace-grid"><section class="panel"><div class="panel-title"><div><h2>Workflow event sequence</h2><p class="panel-subtitle">Select a step to see its result.</p></div>${badge(`${rows.length} events`, "blue")}</div><div class="segmented" aria-label="Trace draft selection"><button data-draft="initial" class="${state.draft === "initial" ? "selected" : ""}">Original draft</button><button data-draft="revised" class="${state.draft === "revised" ? "selected" : ""}">Quantity revision</button></div><div class="trace-list">${rows.map((row) => `<button class="trace-event" data-detail="${rowDetail(title(row.event), row)}"><span class="trace-node">${row.seq}</span><span><strong>${esc(title(row.event))}</strong><small>${esc(traceSummary(row))}</small></span>${icon("chevron")}</button>`).join("")}</div></section>${summary}</div>`;
  return html;
}
function traceSummary(row) {
  const b = row.body || {};
  if (row.event === "draft.queued")
    return `Revision ${b.revision} is ready to run`;
  if (row.event === "evidence.retrieve")
    return `${b.chunks.length} passages · ETL v${b.etl_publication} · ${b.cache_hit ? "cached sources rechecked" : "source snapshot saved"}`;
  if (row.event === "engineering.complete")
    return `${dollars(b.costing.total_cost_cents)} cost · ${num(b.risk.capacity_shortfall_units)} units of capacity gap`;
  if (row.event === "business.complete")
    return `${b.options.length} pricing options · totals calculated in cents`;
  if (row.event === "draft.validated")
    return "Quote totals and source conditions checked";
  if (row.event === "manager.revision_invalidates_approval")
    return `Old approval invalidated · revision ${b.next_revision} queued`;
  if (row.event === "manager.approved_internal")
    return `${title(b.option_id)} approved for internal review`;
  if (row.event === "manager.follow_up")
    return `${title(b.topic)} · answered from the existing draft`;
  return "Open this step to inspect its recorded result";
}
function eventDetail(row) {
  const b = row.body || {};
  let fields = [];
  if (row.event === "draft.queued") fields = [["Revision", b.revision]];
  if (row.event === "evidence.retrieve")
    fields = [
      ["Retrieved passages", b.chunks.length],
      ["ETL version", b.etl_publication],
      [
        "Source access",
        b.cache_hit ? "Cached evidence rechecked" : "Scoped snapshot captured",
      ],
    ];
  if (row.event === "engineering.complete")
    fields = [
      ["Unit cost", dollars(b.costing.unit_cost_cents)],
      ["Total cost", dollars(b.costing.total_cost_cents)],
      ["Capacity gap", `${num(b.risk.capacity_shortfall_units)} units`],
      ["Source conditions", b.handoff_conditions.length],
    ];
  if (row.event === "business.complete")
    return `<dl class="context-list">${b.options.map((option) => contextRow(title(option.option_id), `${dollars(option.unit_price_cents)} / unit · ${option.margin_allowed ? "within margin policy" : "below margin floor"}`)).join("")}</dl>`;
  if (row.event === "draft.validated")
    return '<div class="compact-note">The checked draft is bound to its exact content. A later change requires a new check and approval.</div>';
  if (row.event === "manager.approved_internal")
    fields = [
      ["Option", title(b.option_id)],
      ["Revision", b.revision],
      ["Scope", "Internal review only"],
    ];
  if (row.event === "manager.revision_invalidates_approval")
    fields = [
      ["Next revision", b.next_revision],
      ["Previous approval", "Invalidated"],
    ];
  if (row.event === "manager.follow_up")
    fields = [
      ["Question topic", title(b.topic)],
      ["Evidence", "Existing draft reused"],
    ];
  return fields.length
    ? `<dl class="context-list">${fields.map(([label, value]) => contextRow(label, value)).join("")}</dl>`
    : "";
}
function gatesPage() {
  const a = flow(),
    v = e(),
    faults = v.agent_eval;
  const localPass = v.passed && state.data.freshness.current && faults?.passed;
  let html = heading(
    "RELEASE GATES",
    "What can move forward?",
    "Test results, proposal approval and model release are separate decisions.",
  );
  html += `<div class="wide-grid">${[
    [
      "shield",
      "Local checks",
      `${num(v.unit_tests?.count)} tests and recorded workflow checks.`,
      localPass ? "Passed" : "Review required",
      localPass ? "" : "amber",
    ],
    [
      "users",
      "Revised proposal",
      "18,000 units leave a 4,000-unit capacity gap.",
      "Capacity review needed",
      "amber",
    ],
    [
      "gate",
      "Production release",
      "Real model evaluation, label review and live integration checks remain open.",
      "Not qualified",
      "muted",
    ],
  ]
    .map(
      ([i, name, description, status, tone]) =>
        `<article class="panel gate-card"><div class="gate-icon">${icon(i)}</div><h3>${name}</h3><p>${description}</p>${badge(status, tone)}</article>`,
    )
    .join(
      "",
    )}</div><section class="panel full-panel"><div class="panel-title"><h2>Release checklist</h2>${badge("Customer sending disabled", "muted")}</div>${disclosure("Recorded verification", `${checklist({ unit_tests_passed: v.unit_tests?.passed, no_skipped_full_suite_tests: v.unit_tests?.skipped === 0, workflow_invariants_passed: a?.passed, controlled_faults_rejected_as_expected: faults?.passed, source_hashes_match: state.data.freshness.current })}${detailButton("Inspect verification metadata", { verified_at_utc: v.verified_at_utc, unit_tests: v.unit_tests, freshness: state.data.freshness, source_sha256: v.source_sha256 })}`, localPass ? "Passed" : "Review required")}${disclosure("Publication status", `<dl class="context-list">${contextRow("Local candidate", state.data.local_state.uncommitted_changes === null ? "Not assessed" : state.data.local_state.uncommitted_changes ? "Uncommitted changes" : "Committed")}${contextRow("Hosted CI", "Not assessed for this candidate")}${contextRow("Deployment", "Not performed")}</dl>`)}<p class="legend-note">Local synthetic evidence. Refresh reloads reports; it does not run tests, approve quotes or deploy.</p></section>`;
  return html;
}
function render() {
  if (!state.data) return;
  state.details = [];
  state.page = sections.some((x) => x[0] === location.hash.slice(1))
    ? location.hash.slice(1)
    : "overview";
  nav.innerHTML = sections
    .map(
      ([id, name, i]) =>
        `<a href="#${id}" class="nav-item ${id === state.page ? "active" : ""}" ${id === state.page ? 'aria-current="page"' : ""} title="${name}">${icon(i)}<span>${name}</span></a>`,
    )
    .join("");
  document.querySelector("#breadcrumb-current").textContent = sections.find(
    (x) => x[0] === state.page,
  )[1];
  main.innerHTML = {
    overview,
    agents,
    data: dataPage,
    risk: riskPage,
    traces: tracesPage,
    gates: gatesPage,
  }[state.page]();
  document.querySelector("#footer").innerHTML =
    `<span>Recorded local evidence · Synthetic data</span><span>Read-only · No customer dispatch</span>`;
}
async function load() {
  const button = document.querySelector("#refresh");
  button.disabled = true;
  try {
    const response = await fetch("/api/evaluation", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok)
      throw Error(data.error || "Evidence could not be loaded.");
    state.data = data;
    document.querySelector("#workbench-link").hidden = !data.showcase_enabled;
    document.querySelector("#export").disabled = false;
    render();
  } catch (error) {
    state.data = null;
    document.querySelector("#export").disabled = true;
    document.querySelector("#footer").textContent =
      "Evidence unavailable · No current evaluation claim";
    main.innerHTML = `<div class="empty-state glass"><span class="eyebrow">EVIDENCE UNAVAILABLE</span><h1>Let’s load a verified run.</h1><p>${esc(error.message)}</p><p>Run <code>python -m scripts.verify --agents</code>, then refresh evidence.</p></div>`;
  } finally {
    button.disabled = false;
  }
}
document.addEventListener("click", (event) => {
  const detail = event.target.closest("[data-detail]");
  if (detail) {
    openDetail(detail.dataset.detail);
    return;
  }
  const draft = event.target.closest("[data-draft]");
  if (draft) {
    state.draft = draft.dataset.draft;
    render();
  }
});
document.addEventListener("keydown", (event) => {
  if (
    event.target.tagName === "TR" &&
    event.target.dataset.detail &&
    (event.key === "Enter" || event.key === " ")
  ) {
    event.preventDefault();
    openDetail(event.target.dataset.detail);
  }
});
document.querySelector("#refresh").addEventListener("click", load);
document
  .querySelector("#detail-close")
  .addEventListener("click", () =>
    document.querySelector("#detail-dialog").close(),
  );
document.querySelector("#detail-dialog").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    const box = event.currentTarget.getBoundingClientRect();
    if (
      event.clientX < box.left ||
      event.clientX > box.right ||
      event.clientY < box.top ||
      event.clientY > box.bottom
    )
      event.currentTarget.close();
  }
});
document.querySelector("#export").innerHTML = icon("download");
document.querySelector("#refresh-icon").innerHTML = icon("refresh");
document.querySelector("#export").addEventListener("click", () => {
  if (!state.data) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(state.data, null, 2)], {
      type: "application/json",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = `evaluation-${state.data.snapshot_id.slice(0, 10)}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener("hashchange", () => {
  render();
  window.scrollTo({ top: 0 });
});
load();

function managerFeedbackPanel(result) {
  if (!result) return absent("Manager feedback evaluation");
  return `<section class="panel full-panel"><div class="panel-title"><div><h2>When the manager changes the plan</h2><p class="panel-subtitle">Reject → revise quantity → recalculate → review again</p></div>${badge(result.passed ? "Checks passed" : "Review required", result.passed ? "" : "amber")}</div><div class="feedback-result"><strong>12,000 → ${num(result.revised_quantity)} units</strong><span>${num(result.capacity_shortfall_units)}-unit capacity gap · approval blocked</span></div><p class="legend-note">Feedback stays pending review. A manager’s opinion does not automatically become a training label.</p>${disclosure("Inspect feedback checks", `${checklist(result.checks)}${detailButton("Inspect feedback binding", result)}`, checkCount(result.checks))}</section>`;
}
function modelContractsPanel(report) {
  if (!report)
    return disclosure(
      "Model integration",
      '<p class="legend-note">Contract evidence is unavailable.</p>',
      "Not run",
    );
  const body = `<div class="pills">${badge(`${num(report.mock_sdk_calls)} mock SDK calls`, "blue")}${badge(`${num(report.real_inference_calls)} real inference calls`, "muted")}${badge("Model quality not measured", "amber")}</div>${checklist(report.checks)}<div class="table-wrap spaced"><table><thead><tr><th>Split</th><th>Cases</th><th>Rules checks</th><th>Model quality</th></tr></thead><tbody>${Object.entries(
    report.splits,
  )
    .map(
      ([name, row]) =>
        `<tr><td>${esc(title(name))}</td><td>${num(row.case_count)}</td><td>${num(row.rules_passed_count)} / ${num(row.case_count)}</td><td>Not measured</td></tr>`,
    )
    .join(
      "",
    )}</tbody></table></div><p class="legend-note">Synthetic labels await independent review. Mock responses test the wiring, not model quality.</p><div class="spaced">${detailButton("Inspect model contract report", report)}</div>`;
  return disclosure(
    "Offline model integration",
    body,
    report.passed ? "Contracts passed · rollout locked" : "Review contracts",
  );
}
