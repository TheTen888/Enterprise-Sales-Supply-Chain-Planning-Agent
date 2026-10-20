const state = {
  data: null,
  selected: null,
  busy: false,
  answer: null,
  timer: null,
  forms: {},
};
const content = document.querySelector("#content");
const message = document.querySelector("#message");
const esc = (value) =>
  String(value ?? "—").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const number = (value) => Number(value).toLocaleString("en-US");
const money = (cents) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    cents / 100,
  );
const badge = (text, tone = "") =>
  `<span class="badge ${tone}">${esc(text)}</span>`;
const names = {
  retain_price: "Keep current price",
  customer_request: "Customer requests 5% off",
  counteroffer: "Policy-constrained counteroffer",
};
const statuses = {
  queued: "Queued",
  running: "Generating draft",
  needs_review: "Ready for internal review",
  needs_capacity_review: "Capacity review required",
  approved_internal: "Approved internally",
  superseded: "Superseded",
  rejected: "Revision requested",
  failed: "Generation failed",
  invalidated: "Source changed",
};
const requestId = () => crypto.randomUUID().replaceAll("-", "");
const current = () =>
  state.data.jobs.find((job) => job.job_id === state.selected);

function notify(text, error = false) {
  message.innerHTML = text
    ? `<div class="session-note ${error ? "session-error" : ""}">${esc(text)}</div>`
    : "";
}

function render() {
  const data = state.data;
  document.querySelector("#export-session").disabled = false;
  if (!data.jobs.length) {
    content.innerHTML = `<section class="panel intro-card"><span class="eyebrow">CUSTOMER A · PROJECT A</span><h2>A customer asks for 5% off.<br>Should the manager agree?</h2><p>Read the latest order, customer email and engineering constraints. Let the two deterministic roles prepare three pricing options, then review the numbers and sources.</p><div class="intro-metrics"><div><small>Published order</small><strong>${number(data.facts.quantity)} units</strong></div><div><small>Current selling price</small><strong>${money(data.facts.unit_price_cents)}</strong></div><div><small>Approved unit cost</small><strong>${money(data.facts.unit_cost_cents)}</strong></div></div><div class="steps"><span>Scoped evidence</span><span>Engineering checks</span><span>Business options</span><span>Manager decision</span></div><button class="primary" data-action="generate" ${state.busy ? "disabled" : ""}>${state.busy ? "Generating…" : "Generate quote options"}</button><p class="legend-note">No LLM or cloud service is called. The 10% margin floor is a fictional demo policy.</p></section>`;
    return;
  }
  if (!current()) state.selected = data.jobs.at(-1).job_id;
  const job = current();
  const draft = job.draft;
  const form = state.forms[job.job_id] || {
    quantity: 18000,
    reason_code: "pricing_assumption",
    note: "",
  };
  const pending = ["queued", "running"].includes(job.status);
  const active = [
    "needs_review",
    "needs_capacity_review",
    "approved_internal",
  ].includes(job.status);
  const revisable = [
    "needs_review",
    "needs_capacity_review",
    "approved_internal",
    "rejected",
  ].includes(job.status);
  let html = `<div class="draft-toolbar"><label>Draft history <select id="draft-select" aria-label="Select draft">${data.jobs.map((row, i) => `<option value="${esc(row.job_id)}" ${row.job_id === job.job_id ? "selected" : ""}>Draft ${i + 1} · Rev ${row.revision} · ${esc(statuses[row.status] || row.status)}</option>`).join("")}</select></label><button class="secondary" data-action="generate" ${state.busy ? "disabled" : ""}>New draft</button></div>`;
  if (!draft) {
    content.innerHTML =
      html +
      `<section class="panel workbench-empty">${pending ? '<span class="loader"></span>' : ""}<h2 class="${pending ? "" : "error-title"}">${pending ? "The local worker is preparing this draft." : "This draft did not publish."}</h2><p>${pending ? "Evidence → Engineering → Business → Validation" : "Start a new draft and inspect the recorded events below."}</p>${events(job)}</section>`;
    return;
  }
  const risk = draft.engineering.risk;
  const canApprove = job.status === "needs_review" && !state.busy;
  const selectedApproval = job.approval_valid ? job.approval.option_id : null;
  const canReject =
    ["needs_review", "needs_capacity_review"].includes(job.status) &&
    !state.busy;
  html += `<div class="workbench-layout"><div class="workbench-column"><section class="panel"><div class="draft-status"><strong>Customer A · Project A</strong>${badge(statuses[job.status] || job.status, job.status === "needs_review" || job.approval_valid ? "" : "amber")}</div><div class="draft-id">${esc(draft.scope.entity_id)} · Revision ${job.revision} · ${esc(job.job_id.slice(0, 12))}</div><div class="live-metrics"><div><small>Scenario quantity</small><strong>${number(draft.quantity)} units</strong></div><div><small>Total cost</small><strong>${money(draft.engineering.costing.total_cost_cents)}</strong></div><div><small>Capacity gap</small><strong>${number(risk.capacity_shortfall_units)} units</strong></div></div><p class="legend-note">${draft.scenario_kind === "manager_what_if" ? "Manager what-if only." : "Published order scenario."} ETL quantity stays ${number(data.facts.quantity)}. ${risk.outside_training_range.length ? "Quantity exceeds the model training range. " : ""}Synthetic risk score ${risk.risk_score.toFixed(2)} / 100 is advisory; the model is unpromoted.</p>${risk.requires_capacity_review ? '<div class="session-note session-warning">Shared-line demand exceeds usable capacity. Pricing can pass while delivery approval remains blocked.</div>' : ""}</section>`;
  html += `<section class="panel"><div class="panel-title"><h2>Compare pricing options</h2>${badge("Exact cent arithmetic", "blue")}</div><div class="quote-options">${draft.business.options.map((option) => `<article class="quote-card ${option.option_id === "counteroffer" ? "recommended" : ""}"><div class="quote-top"><span class="quote-name">${names[option.option_id]}</span><span class="quote-price">${money(option.unit_price_cents)} <small>/ unit</small></span></div><div class="quote-numbers"><span>Revenue<strong>${money(option.revenue_cents)}</strong></span><span>Gross profit<strong>${money(option.gross_profit_cents)}</strong></span><span>Margin<strong>${(option.margin_bps / 100).toFixed(2)}%</strong></span></div><div class="quote-bottom">${badge(option.margin_allowed ? "Pricing check passed" : "Below margin floor", option.margin_allowed ? "" : "amber")}<button class="primary ${option.option_id === "counteroffer" ? "" : "subtle"}" data-approve="${esc(option.option_id)}" aria-label="Approve ${esc(names[option.option_id])} internally" ${!canApprove || !option.margin_allowed ? "disabled" : ""}>${selectedApproval === option.option_id ? "Approved internally" : "Approve internally"}</button></div></article>`).join("")}</div><p class="legend-note">Internal approval binds this exact revision and payload. It never sends a customer quote. A new revision invalidates the old approval.</p></section>`;
  html += `<section class="panel"><div class="panel-title"><h2>Evidence behind the options</h2>${badge(`${draft.engineering.constraints.length} conditions`, "blue")}</div><div class="evidence-list">${draft.engineering.constraints.map((row) => `<details class="evidence-item"><summary>${esc(row.document_id)} · v${row.version} · ${esc(row.id.replaceAll("_", " "))}</summary><p>${esc(row.text)}</p><code>${esc(row.chunk_id)}<br>Source ${esc(row.source_hash)}</code></details>`).join("")}</div></section><section class="panel"><div class="panel-title"><h2>Recorded execution</h2>${badge("This session", "muted")}</div>${events(job)}</section></div>`;
  html += `<div class="workbench-column"><section class="panel"><div class="panel-title"><h2>Test a quantity change</h2></div><form id="quantity-form" class="form-stack"><label>Scenario units<input name="quantity" aria-label="Scenario units" type="number" min="1" max="${data.policy.maximum_scenario_quantity}" step="1" value="${esc(form.quantity)}" required ${!revisable || state.busy ? "disabled" : ""}></label><button class="primary" type="submit" ${!revisable || state.busy ? "disabled" : ""}>Recalculate a new revision</button></form><p class="legend-note">Reuses approved unit cost and the frozen model. Recalculates totals, shared capacity and risk. Extra volume is not a signed customer commitment.</p></section>`;
  html += `<section class="panel"><div class="panel-title"><h2>Ask about this draft</h2>${badge("Guided follow-ups", "muted")}</div><div class="question-actions">${[
    ["discount_limit", "Why this price?"],
    ["volume_change", "What changed?"],
    ["delivery_risk", "Can we deliver?"],
  ]
    .map(
      ([topic, label]) =>
        `<button class="question-button" data-topic="${topic}" ${!active || state.busy ? "disabled" : ""}>${label}</button>`,
    )
    .join(
      "",
    )}</div>${state.answer ? answer(state.answer) : '<p class="legend-note">Three supported questions read the existing draft. They do not trigger new agent analysis or act as a general chatbot.</p>'}</section>`;
  html += `<section class="panel"><div class="panel-title"><h2>Request a revision</h2></div><form id="feedback-form" class="form-stack"><label>Reason<select name="reason_code" aria-label="Feedback reason" ${!canReject ? "disabled" : ""}>${Object.entries(
    data.feedback_reasons,
  )
    .map(
      ([key, label]) =>
        `<option value="${key}" ${key === form.reason_code ? "selected" : ""}>${esc(label)}</option>`,
    )
    .join(
      "",
    )}</select></label><label>What should be reviewed?<textarea name="note" aria-label="What should be reviewed?" minlength="5" maxlength="500" placeholder="For example: The customer mentioned 18,000 units, but the extra volume is not signed." required ${!canReject ? "disabled" : ""}>${esc(form.note)}</textarea></label><button class="secondary" type="submit" ${!canReject ? "disabled" : ""}>Reject draft & save feedback</button></form><p class="legend-note">Feedback is linked to the exact draft and evidence, then held for review. A manager's disagreement is not automatically a model-error label or training data.</p>${job.feedback.map((row) => `<article class="feedback-item">${badge("Pending review", "amber")}<p>${esc(row.note)}</p><small>${esc(data.feedback_reasons[row.reason_code])} · Revision ${row.revision}<br>Payload ${esc(row.payload_hash.slice(0, 14))}…</small></article>`).join("")}</section><div class="session-note">This is a live, local workflow. <a class="text-link" href="/#agents">Evaluation Studio</a> shows a separate, recorded regression run. Export this session to review its actual drafts, feedback and traces.</div></div></div>`;
  content.innerHTML = html;
}

function events(job) {
  return `<div class="session-events">${job.trace.map((row) => `<details><summary>${row.seq} · ${esc(row.event.replaceAll(".", " ").replaceAll("_", " "))}</summary><pre class="detail-json">${esc(JSON.stringify(row.body, null, 2))}</pre></details>`).join("")}</div>`;
}

function answer(result) {
  const value = result.answer;
  let text;
  if (result.topic === "discount_limit")
    text = `The requested ${money(value.requested.unit_price_cents)} leaves ${(value.requested.margin_bps / 100).toFixed(2)}% gross margin. The demo floor is ${(value.minimum_margin_bps / 100).toFixed(0)}%. The counteroffer is ${money(value.counteroffer.unit_price_cents)}. ${value.reason}.`;
  else if (result.topic === "volume_change")
    text = `The published order stays at ${number(value.published_quantity)} units; this scenario uses ${number(value.scenario_quantity)}. Recalculated: ${value.recalculated.map((x) => x.replaceAll("_", " ")).join(", ")}. ${value.reason}.`;
  else
    text = `Shared-line load is ${(value.features.capacity_load_ratio * 100).toFixed(2)}%. Capacity shortfall: ${number(value.capacity_shortfall_units)} units. Schedule slack: ${value.features.schedule_slack_days} production slots. ${value.requires_capacity_review ? "Planning must resolve the gap before approval." : "The aggregate capacity check passes; this does not guarantee every order will ship on time."}`;
  return `<div class="answer-box"><h3>Answer from the current draft</h3>${esc(text)}<p class="legend-note">Sources: ${esc([...new Set(result.citations.map((row) => `${row.document_id} v${row.version}`))].join(" · "))}</p></div>`;
}

async function load() {
  clearTimeout(state.timer);
  const response = await fetch("/api/showcase", { cache: "no-store" });
  const data = await response.json();
  if (!response.ok) throw Error(data.error);
  state.data = data;
  render();
  if (data.jobs.some((job) => ["queued", "running"].includes(job.status)))
    state.timer = setTimeout(
      () => load().catch((error) => notify(error.message, true)),
      600,
    );
}

async function act(command) {
  if (state.busy) return;
  const quantityForm = document.querySelector("#quantity-form");
  const feedbackForm = document.querySelector("#feedback-form");
  if (state.selected && quantityForm && feedbackForm) {
    state.forms[state.selected] = {
      quantity: quantityForm.elements.quantity.value,
      reason_code: feedbackForm.elements.reason_code.value,
      note: feedbackForm.elements.note.value,
    };
  }
  state.busy = true;
  render();
  notify("Working on this local draft…");
  try {
    const response = await fetch("/api/showcase/actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(command),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error);
    if (command.action === "explain") state.answer = result;
    else {
      state.answer = null;
      if (result.job_id) state.selected = result.job_id;
    }
    notify(
      command.action === "reject"
        ? "Feedback saved for review. This draft cannot be approved."
        : command.action === "approve"
          ? "Approved for internal review only. No customer message was sent."
          : "Local action completed.",
    );
  } catch (error) {
    notify(error.message, true);
  } finally {
    state.busy = false;
    await load().catch((error) => notify(error.message, true));
  }
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button || !state.data) return;
  if (button.dataset.action === "generate")
    act({ action: "generate", request_id: requestId() });
  if (button.dataset.approve)
    act({
      action: "approve",
      job_id: state.selected,
      option_id: button.dataset.approve,
    });
  if (button.dataset.topic)
    act({
      action: "explain",
      job_id: state.selected,
      topic: button.dataset.topic,
    });
});
document.addEventListener("change", (event) => {
  if (event.target.id === "draft-select") {
    state.selected = event.target.value;
    state.answer = null;
    render();
  }
});
document.addEventListener("submit", (event) => {
  if (!["quantity-form", "feedback-form"].includes(event.target.id)) return;
  event.preventDefault();
  const data = new FormData(event.target);
  if (event.target.id === "quantity-form")
    act({
      action: "revise",
      request_id: requestId(),
      job_id: state.selected,
      quantity: Number(data.get("quantity")),
    });
  else
    act({
      action: "reject",
      request_id: requestId(),
      job_id: state.selected,
      reason_code: data.get("reason_code"),
      note: data.get("note"),
    });
});
document
  .querySelector("#export-session")
  .addEventListener("click", async () => {
    try {
      const response = await fetch("/api/showcase/export", {
        cache: "no-store",
      });
      if (!response.ok) throw Error("Session export is unavailable.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "local-decision-session.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      notify(error.message, true);
    }
  });
load().catch((error) => {
  content.innerHTML =
    '<section class="panel workbench-empty"><h2>The local session is unavailable.</h2></section>';
  notify(error.message, true);
});
