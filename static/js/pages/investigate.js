import { api } from "../api.js";
import { el, clear, kpi, panel, chartInto, COLORS, axisOpts, fmt, riskBadge, classTag, dataTable, emptyState, errorState, skeleton, toast } from "../ui.js";

export async function mount(root, ctx) {
  const result = el("div", {});
  const input = el("input", { class: "input", id: "txn-id", placeholder: "Transaction ID, e.g. 542", inputmode: "numeric", "aria-label": "Transaction ID", style: "min-width:240px", value: ctx.params[0] || "" });
  const go = (id) => { const n = Number(id); if (!Number.isInteger(n) || n < 1) { clear(result).append(emptyState("Invalid transaction ID", "Enter a positive whole number, e.g. 542.")); return; } if (ctx.params[0] !== String(n)) history.replaceState(null, "", `#/investigate/${n}`); ctx.params = [String(n)]; investigate(n); };
  root.append(el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Transaction Investigation Center"), el("p", {}, "Inspect a transaction, its model decision, the exact feature contributions behind it, and how each model version scored it.")),
    el("form", { class: "toolbar", onsubmit: (e) => { e.preventDefault(); go(input.value); } }, input, el("button", { class: "btn primary", type: "submit" }, "Investigate"))), result);

  async function investigate(id) {
    clear(result).append(skeleton(160), el("div", { style: "height:14px" }), skeleton(260));
    try {
      const [d, ex, cmp] = await Promise.all([api(`/transactions/${id}`), api(`/transactions/${id}/explain`, { params: { top: 12 } }).catch((e) => ({ error: e })), api(`/transactions/${id}/compare`).catch((e) => ({ error: e }))]);
      render(d, ex, cmp);
    } catch (e) { clear(result).append(e.status === 404 ? emptyState(`Transaction ${id} not found`, "Check the ID and try again.") : errorState(e, () => investigate(id))); }
  }

  function render(d, ex, cmp) {
    const t = d.transaction, lp = d.latest_prediction;
    const featHost = el("div", {}), shapHost = el("div", {});
    const rescore = el("button", { class: "btn", onclick: async (e) => { e.currentTarget.disabled = true; try { await api("/predict", { method: "POST", body: { transaction_id: t.transaction_id } }); toast("Re-scored", `Transaction ${t.transaction_id} scored again`, "ok"); investigate(t.transaction_id); } catch (x) { toast("Re-score failed", x.message, "alert"); e.currentTarget.disabled = false; } } }, "Re-score now");
    clear(result).append(
      el("div", { class: "grid g-kpi" }, kpi({ label: "Amount", value: fmt.money(t.amount), hint: "dataset units" }), kpi({ label: "Actual label", value: t.actual_label || "–", hint: "ground truth from dataset", cls: "accent-truth" }),
        kpi({ label: "Fraud probability", value: lp ? fmt.prob(lp.fraud_probability) : "–", cls: "accent-pred", hint: lp ? `model ${lp.model_version}` : "not scored yet" }),
        kpi({ label: "Prediction", value: lp ? (lp.predicted_class ? "Flagged" : "Clear") : "–", hint: lp ? `threshold ${fmt.num(lp.threshold, 3)}` : "", cls: "accent-pred" }),
        kpi({ label: "Risk level", value: lp ? riskBadge(lp.risk_level) : "–", cls: "accent-pred" })),
      el("div", { class: "grid g-2", style: "margin-top:14px" },
        panel("Why this score? (SHAP explanation)", ex.error ? "" : `Base ${fmt.num(ex.base_value_logit, 2)} → output ${fmt.num(ex.output_logit, 2)} (log-odds)`, shapHost),
        panel("Transaction details", "Anonymised features only – no personal data exists in this dataset", featHost)),
      el("div", { class: "section-label" }, "Prediction history & model versions"),
      el("div", { class: "grid g-2" },
        panel("Prediction history", "Every stored score for this transaction", dataTable({ empty: "No predictions stored yet – use Re-score.", rows: d.history, columns: [{ label: "Processed", render: (r) => fmt.datetime(r.processed_at) }, { key: "model_version", label: "Version" }, { key: "source", label: "Source" }, { label: "Probability", align: "r", render: (r) => fmt.prob(r.fraud_probability) }, { label: "Risk", render: (r) => riskBadge(r.risk_level) }, { label: "Decision", render: (r) => classTag(r.predicted_class) }] }), rescore),
        panel("Model version comparison", cmp.error ? "" : cmp.note, cmp.error ? errorState(cmp.error) : dataTable({ rows: cmp.versions, columns: [{ key: "model_version", label: "Version" }, { label: "Re-scored now", align: "r", render: (r) => (r.rescored_probability === null || r.rescored_probability === undefined ? "n/a" : fmt.prob(r.rescored_probability)) }, { label: "Decision", render: (r) => (r.rescored_class === undefined ? "–" : classTag(r.rescored_class)) }, { label: "Stored score", align: "r", render: (r) => (r.stored_prediction ? fmt.prob(r.stored_prediction.fraud_probability) : "–") }, { label: "Risk", render: (r) => riskBadge(r.risk_level) }] }))));
    if (ex.error) clear(shapHost).append(errorState(ex.error));
    else {
      const c = ex.contributions;
      chartInto(shapHost, { type: "bar", ariaLabel: "Feature contributions", data: { labels: c.map((x) => x.feature), datasets: [{ data: c.map((x) => x.contribution), backgroundColor: c.map((x) => (x.contribution > 0 ? COLORS.high : COLORS.low)), borderRadius: 4 }] }, options: { indexAxis: "y", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (i) => `${i.parsed.x > 0 ? "increases" : "decreases"} fraud risk by ${Math.abs(i.parsed.x).toFixed(2)} log-odds (value ${c[i.dataIndex].value.toFixed(3)})` } } }, scales: { x: axisOpts({ title: { display: true, text: "← lowers risk · raises risk →" } }), y: { grid: { display: false } } } } }, "chart-box tall");
      shapHost.append(el("div", { class: "legend-note" }, "Red bars push the score toward fraud, green toward legitimate. ", ex.method_note));
    }
    featHost.append(el("dl", { class: "kv", style: "margin-bottom:12px" }, el("dt", {}, "Transaction ID"), el("dd", {}, t.transaction_id), el("dt", {}, "Elapsed time (s)"), el("dd", {}, fmt.num(t.transaction_time, 0))),
      el("details", {}, el("summary", { style: "cursor:pointer;color:var(--accent-2)" }, "Show V1–V28 feature values"),
        el("div", { class: "table-wrap", style: "margin-top:8px;max-height:260px" }, el("table", {}, el("tbody", {}, Object.entries(d.features).map(([k, v]) => el("tr", {}, el("td", { class: "mono" }, k.toUpperCase()), el("td", { class: "r num mono" }, Number(v).toFixed(4)))))))),
      el("div", { class: "legend-note" }, d.feature_note));
  }
  if (ctx.params[0]) go(ctx.params[0]); else result.append(emptyState("Enter a transaction ID to begin", "Tip: click any row on the Live Monitoring page to jump here."));
}
