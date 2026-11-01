import { api } from "../api.js";
import { el, clear, kpi, panel, chartInto, COLORS, axisOpts, fmt, emptyState, section, banner } from "../ui.js";

const PRESETS = [["15 min", 15], ["1 hour", 60], ["24 hours", 1440], ["All time", 0]];

export function confusionMatrix(cm, labels = ["Legitimate", "Fraud"]) {
  const cell = (v, kind) => el("div", { class: "cell", style: `background:${kind === "good" ? "var(--low-bg)" : "var(--high-bg)"}` }, el("b", {}, fmt.int(v)), kind === "good" ? "correct" : "error");
  return el("div", {}, el("div", { class: "cm" }, el("div", {}), el("div", { class: "hd" }, `Predicted ${labels[0]}`), el("div", { class: "hd" }, `Predicted ${labels[1]}`),
    el("div", { class: "hd" }, `Actual ${labels[0]}`), cell(cm.tn, "good"), cell(cm.fp, "bad"), el("div", { class: "hd" }, `Actual ${labels[1]}`), cell(cm.fn, "bad"), cell(cm.tp, "good")),
    el("div", { class: "legend-note" }, "FP = false alarm · FN = missed fraud"));
}

export async function mount(root, ctx) {
  let preset = 60, from = "", to = "";
  const hosts = Object.fromEntries(["summary", "insights", "cmLive", "dist", "trend", "hourly", "amount", "prob", "hr", "pr", "roc", "prc"].map((k) => [k, el("div", {})]));
  const dateParams = () => {
    const mv = { model_version: ctx.activeVersion };
    if (from || to) return { ...mv, date_from: from ? new Date(from).toISOString() : undefined, date_to: to ? new Date(to).toISOString() : undefined };
    return preset ? { ...mv, date_from: new Date(Date.now() - preset * 60000).toISOString() } : mv;
  };
  const seg = el("div", { class: "seg", role: "group", "aria-label": "Date range" }, PRESETS.map(([l, m]) => el("button", { "aria-pressed": String(m === preset), onclick: (e) => { preset = m; from = to = ""; fi.value = ti.value = ""; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); load(); } }, l)));
  const fi = el("input", { class: "input", type: "datetime-local", "aria-label": "From" }), ti = el("input", { class: "input", type: "datetime-local", "aria-label": "To" });
  const apply = el("button", { class: "btn", onclick: () => { from = fi.value; to = ti.value; if (from || to) seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false")); load(); } }, "Apply");

  root.append(el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Fraud Intelligence Analytics"), el("p", {}, "Distributions and model quality. Date filters apply to prediction processing time because the source dataset has no real transaction timestamps.")),
    el("div", { class: "toolbar" }, seg, fi, ti, apply)),
    hosts.summary, el("div", { class: "grid g-main", style: "margin-top:14px" }, panel("Analytical summary", "Generated from the numbers above", hosts.insights), panel("Live confusion matrix", "Processed transactions with replay labels", hosts.cmLive)),
    el("div", { class: "section-label" }, "Patterns"),
    el("div", { class: "grid g-2" }, panel("Fraud vs legitimate", "Actual labels vs model decisions", hosts.dist), panel("Fraud detection trend", "Hourly buckets", hosts.trend),
      panel("Hourly transaction pattern", "Hour = hours since dataset start, mod 24", hosts.hourly), panel("Transaction amount distribution", "Count by amount band (dataset units)", hosts.amount),
      panel("Fraud probability distribution", "20 bins · log scale", hosts.prob), panel("High-risk transaction patterns", "High-risk count by amount band", hosts.hr)),
    el("div", { class: "section-label" }, "Model quality (held-out temporal test set)"),
    el("div", { class: "grid g-2" }, panel("Precision & recall comparison", "Candidate models at threshold 0.5 + deployed model at its tuned threshold", hosts.pr), panel("ROC curve", "Deployed model", hosts.roc), panel("Precision-Recall curve", "Deployed model", hosts.prc)));

  let loadId = 0;
  async function load() {
    const id = ++loadId, p = dateParams();
    const live = () => id === loadId;
    section(hosts.summary, () => api("/analytics/summary", { params: p }), (s, h) => {
      if (!live()) return;
      clear(h).append(el("div", { class: "grid g-kpi" }, kpi({ label: "Processed", value: fmt.int(s.processed) }), kpi({ label: "Actual fraud (labels)", value: fmt.int(s.actual_fraud), cls: "accent-truth" }), kpi({ label: "Flagged (predicted)", value: fmt.int(s.predicted_flagged), cls: "accent-pred" }),
        kpi({ label: "Precision", value: fmt.pct(s.precision) }), kpi({ label: "Recall", value: fmt.pct(s.recall) }), kpi({ label: "F1", value: fmt.pct(s.f1) }), kpi({ label: "High-risk", value: fmt.int(s.high_risk) })));
      const cm = s.confusion_matrix;
      clear(hosts.cmLive).append(s.processed ? confusionMatrix(cm) : emptyState("No processed transactions in this range"));
      const lines = s.processed ? [`${fmt.int(s.processed)} transactions were scored in this window; ${fmt.int(s.predicted_flagged)} (${fmt.pct(s.predicted_flagged / s.processed)}) were flagged.`,
        s.actual_fraud ? `Of ${fmt.int(s.actual_fraud)} actual fraud cases, ${fmt.int(cm.tp)} were caught (recall ${fmt.pct(s.recall)}) and ${fmt.int(cm.fn)} were missed.` : "No actual fraud labels occurred in this window.",
        cm.tp + cm.fp ? `${fmt.int(cm.fp)} flagged transactions were false alarms (precision ${fmt.pct(s.precision)}).` : "Nothing was flagged in this window.",
        s.held_out && s.held_out.processed ? `Held-out (unseen by the model): ${fmt.int(s.held_out.processed)} transactions, ${s.held_out.caught} of ${s.held_out.actual_fraud} fraud caught, ${s.held_out.false_alarms} false alarms.` : "No held-out (unseen) transactions in this range – the figures above can include training data and look better than real performance.",
        `Mean fraud probability: ${fmt.prob(s.avg_probability)}.`, "If PRODUCER_FRAUD_BOOST > 0 the replay over-samples fraud, so flagged share is higher than in real traffic."] : ["No data in the selected range."];
      clear(hosts.insights).append(el("ul", { style: "margin:0;padding-left:18px;display:grid;gap:8px" }, lines.map((l) => el("li", {}, l))));
    }, { skeletonHeight: 90 });
    section(hosts.dist, async () => ({ s: await api("/analytics/summary", { params: p }) }), ({ s }) => {
      if (!live()) return; if (!s.processed) return clear(hosts.dist).append(emptyState("No data in this range"));
      chartInto(hosts.dist, { type: "bar", ariaLabel: "Fraud vs legitimate", data: { labels: ["Actual fraud", "Flagged", "Caught (TP)", "False alarms (FP)", "Missed (FN)"], datasets: [{ data: [s.actual_fraud, s.predicted_flagged, s.confusion_matrix.tp, s.confusion_matrix.fp, s.confusion_matrix.fn], backgroundColor: [COLORS.violet, COLORS.accent, COLORS.low, COLORS.med, COLORS.high], borderRadius: 6 }] }, options: { plugins: { legend: { display: false } }, scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }) } } });
    });
    section(hosts.trend, () => api("/dashboard/trends", { params: { bucket: "hour", window_hours: 72 } }), (t) => {
      if (!live()) return; if (!t.points.length) return clear(hosts.trend).append(emptyState("No scoring events yet"));
      chartInto(hosts.trend, { type: "line", ariaLabel: "Fraud detection trend", data: { labels: t.points.map((x) => new Date(x.bucket).toLocaleString([], { hour12: false, month: "short", day: "numeric", hour: "2-digit" })), datasets: [{ label: "Flagged", data: t.points.map((x) => x.flagged), borderColor: COLORS.high, tension: .3, pointRadius: 2 }, { label: "Actual fraud", data: t.points.map((x) => x.actual_fraud), borderColor: COLORS.violet, tension: .3, pointRadius: 2 }, { label: "Events", data: t.points.map((x) => x.events), borderColor: COLORS.accent, borderDash: [4, 4], pointRadius: 0, yAxisID: "y2" }] }, options: { scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }), y2: { position: "right", grid: { display: false }, beginAtZero: true } } } });
    });
    section(hosts.hourly, () => api("/analytics/hourly", { params: p }), (d) => {
      if (!live()) return;
      chartInto(hosts.hourly, { type: "bar", ariaLabel: "Hourly pattern", data: { labels: d.points.map((x) => x.hour), datasets: [{ label: "Transactions", data: d.points.map((x) => x.transactions), backgroundColor: "rgba(79,140,255,.55)", borderRadius: 4 }, { type: "line", label: "Flagged", data: d.points.map((x) => x.flagged), borderColor: COLORS.high, pointRadius: 2, tension: .3, yAxisID: "y2" }] }, options: { scales: { x: axisOpts({ title: { display: true, text: "hour of cycle" } }), y: axisOpts({ beginAtZero: true }), y2: { position: "right", grid: { display: false }, beginAtZero: true } } } });
    });
    section(hosts.amount, () => api("/analytics/amount-distribution", { params: p }), (d) => {
      if (!live()) return;
      chartInto(hosts.amount, { type: "bar", ariaLabel: "Amount distribution", data: { labels: d.buckets.map((b) => b.label), datasets: [{ label: "Transactions", data: d.buckets.map((b) => b.transactions), backgroundColor: "rgba(79,140,255,.55)", borderRadius: 4 }, { label: "Flagged", data: d.buckets.map((b) => b.flagged), backgroundColor: COLORS.high, borderRadius: 4 }] }, options: { scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }) } } });
    });
    section(hosts.prob, () => api("/analytics/probability-distribution", { params: p }), (d) => {
      if (!live()) return;
      chartInto(hosts.prob, { type: "bar", ariaLabel: "Probability distribution", data: { labels: d.bins.map((b) => b.from.toFixed(2)), datasets: [{ label: "Predictions", data: d.bins.map((b) => b.count), backgroundColor: "rgba(79,140,255,.6)" }, { label: "Actual fraud", data: d.bins.map((b) => b.actual_fraud), backgroundColor: COLORS.violet }] }, options: { scales: { x: axisOpts(), y: { ...axisOpts(), type: "logarithmic", min: 0.8 } } } });
    });
    section(hosts.hr, () => api("/analytics/high-risk-patterns", { params: p }), (d) => {
      if (!live()) return; if (!d.count) return clear(hosts.hr).append(emptyState("No high-risk transactions in this range"));
      chartInto(hosts.hr, { type: "bar", ariaLabel: "High-risk by amount band", data: { labels: d.by_amount.map((b) => b.label), datasets: [{ label: `High-risk (≥ ${d.high_risk_threshold})`, data: d.by_amount.map((b) => b.count), backgroundColor: COLORS.high, borderRadius: 4 }] }, options: { scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }) } } });
    });
  }
  load();
  section(hosts.pr, () => api("/model/metrics"), (m) => {
    const names = Object.keys(m.comparison).filter((n) => m.comparison[n]["test_at_0.5"]);
    const get = (n) => m.comparison[n]["test_at_0.5"];
    const labels = [...names.map((n) => (n === "XGBoost_tuned" ? "XGBoost (tuned)" : n)), "Deployed @ tuned thr."];
    chartInto(hosts.pr, { type: "bar", ariaLabel: "Precision and recall by model", data: { labels, datasets: [{ label: "Precision", data: [...names.map((n) => get(n).precision), m.test.precision], backgroundColor: COLORS.accent, borderRadius: 4 }, { label: "Recall", data: [...names.map((n) => get(n).recall), m.test.recall], backgroundColor: COLORS.cyan, borderRadius: 4 }] }, options: { scales: { x: axisOpts(), y: axisOpts({ min: 0, max: 1 }) } } });
    chartInto(hosts.roc, { type: "line", ariaLabel: "ROC curve", data: { datasets: [{ label: `ROC (AUC ${m.test.roc_auc.toFixed(3)})`, data: m.roc_curve.map(([x, y]) => ({ x, y })), borderColor: COLORS.accent, pointRadius: 0, fill: true, backgroundColor: "rgba(79,140,255,.12)" }, { label: "Chance", data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], borderColor: COLORS.grid, borderDash: [4, 4], pointRadius: 0 }] }, options: { scales: { x: { type: "linear", min: 0, max: 1, title: { display: true, text: "False positive rate" }, grid: { color: COLORS.grid } }, y: { type: "linear", min: 0, max: 1, title: { display: true, text: "True positive rate" }, grid: { color: COLORS.grid } } } } });
    chartInto(hosts.prc, { type: "line", ariaLabel: "Precision-recall curve", data: { datasets: [{ label: `PR (AP ${m.test.pr_auc.toFixed(3)})`, data: m.pr_curve.map(([x, y]) => ({ x, y })), borderColor: COLORS.violet, pointRadius: 0, fill: true, backgroundColor: "rgba(167,139,250,.12)" }, { label: "Deployed operating point", data: [{ x: m.test.recall, y: m.test.precision }], borderColor: COLORS.high, backgroundColor: COLORS.high, pointRadius: 6, showLine: false }] }, options: { scales: { x: { type: "linear", min: 0, max: 1, title: { display: true, text: "Recall" }, grid: { color: COLORS.grid } }, y: { type: "linear", min: 0, max: 1.02, title: { display: true, text: "Precision" }, grid: { color: COLORS.grid } } } } });
  });
  return () => { loadId = -1; };
}
