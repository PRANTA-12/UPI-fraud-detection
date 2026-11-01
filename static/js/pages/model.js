import { api } from "../api.js";
import { el, clear, kpi, panel, chartInto, COLORS, axisOpts, fmt, dataTable, statusBadge, banner, section, emptyState } from "../ui.js";
import { confusionMatrix } from "./analytics.js";

export async function mount(root, ctx) {
  const H = Object.fromEntries(["info", "metrics", "cm", "compare", "imp", "hist", "dist", "drift"].map((k) => [k, el("div", {})]));
  root.append(el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "AI Model Intelligence"), el("p", {}, "Everything here is read from versioned training artifacts, the experiment record and live prediction data – nothing is hard-coded."))),
    banner("Trained on the public Credit Card Fraud dataset (anonymised V1–V28). Metrics are from a temporal hold-out with only a few dozen fraud cases, so treat them as indicative, not production guarantees.", "warn"),
    H.info, el("div", { class: "section-label" }, "Evaluation"),
    el("div", { class: "grid g-main" }, panel("Test-set metrics", "Last 20 % of transactions by time · never used for training or threshold selection", H.metrics), panel("Confusion matrix (test)", "At the deployed threshold", H.cm)),
    el("div", { style: "height:14px" }), panel("Model comparison", "5-fold stratified CV on the training period + one-shot test evaluation at 0.5", H.compare),
    el("div", { class: "section-label" }, "Explainability"),
    el("div", { class: "grid g-2" }, panel("Global feature importance", "Mean |SHAP| (TreeSHAP) · larger = more influence on scores", H.imp), panel("Prediction distribution", "Live scores by model version (log scale)", H.dist)),
    el("div", { class: "section-label" }, "Lifecycle & monitoring"),
    el("div", { class: "grid g-2" }, panel("Model performance history", "Registered versions", H.hist), panel("Data drift indicators", "PSI vs training distribution", H.drift)));

  section(H.info, async () => ({ i: await api("/model/info") }), ({ i }) => {
    clear(H.info).append(el("div", { class: "grid g-kpi" }, kpi({ label: "Model", value: i.name, hint: i.algorithm }), kpi({ label: "Active version", value: i.active_version, hint: `viewing ${i.version}` }),
      kpi({ label: "Decision threshold", value: fmt.num(i.threshold, 3), hint: "baked into this version" }), kpi({ label: "Trained", value: fmt.datetime(i.created_at), hint: `${i.training_seconds}s` }),
      kpi({ label: "Training rows", value: fmt.int(i.data.train_rows), hint: `${i.data.train_fraud} fraud · ${i.data.duplicates_removed} duplicates removed` }),
      kpi({ label: "Risk bands", value: `${i.risk_bands.low_max} / ${i.risk_bands.high_min}`, hint: "Low < first ≤ Medium < second ≤ High" })),
      el("details", { style: "margin-top:10px" }, el("summary", { style: "cursor:pointer;color:var(--accent-2)" }, "Training details"),
        el("dl", { class: "kv", style: "margin-top:8px;max-width:760px" }, ...[["Split", i.data.split], ["Threshold policy", i.threshold_policy], ["Class imbalance", `scale_pos_weight = ${fmt.num(i.data.scale_pos_weight, 1)} (no resampling)`], ["Hyperparameters", JSON.stringify(i.hyperparameters)], ["Libraries", JSON.stringify(i.libraries)], ["SHAP vs XGBoost contribs max diff", String(i.shap_consistency_max_abs_diff)]].flatMap(([k, v]) => [el("dt", {}, k), el("dd", { style: "text-align:left;word-break:break-word" }, v)]))));
  });
  section(H.metrics, () => api("/model/metrics"), (m) => {
    const t = m.test;
    clear(H.metrics).append(el("div", { class: "grid g-kpi" }, kpi({ label: "Precision", value: fmt.pct(t.precision) }), kpi({ label: "Recall", value: fmt.pct(t.recall) }), kpi({ label: "F1-score", value: fmt.pct(t.f1) }), kpi({ label: "ROC-AUC", value: fmt.pct(t.roc_auc) }), kpi({ label: "PR-AUC", value: fmt.pct(t.pr_auc) })), el("div", { class: "legend-note" }, m.evaluation_note));
    clear(H.cm).append(confusionMatrix(t.confusion_matrix));
    const rows = Object.entries(m.comparison).map(([n, c]) => ({ n: n === "XGBoost_tuned" ? "XGBoost (tuned) – deployed" : n, cv: c["cv_5fold_at_0.5"], te: c["test_at_0.5"] }));
    clear(H.compare).append(dataTable({ rows, columns: [{ key: "n", label: "Model" }, { label: "CV PR-AUC (mean ± sd)", align: "r", render: (r) => (r.cv ? `${fmt.pct(r.cv.pr_auc.mean)} ± ${fmt.pct(r.cv.pr_auc.std)}` : "–") }, { label: "CV recall", align: "r", render: (r) => (r.cv ? fmt.pct(r.cv.recall.mean) : "–") }, { label: "CV precision", align: "r", render: (r) => (r.cv ? fmt.pct(r.cv.precision.mean) : "–") },
      { label: "Test PR-AUC", align: "r", render: (r) => (r.te ? fmt.pct(r.te.pr_auc) : "–") }, { label: "Test recall", align: "r", render: (r) => (r.te ? fmt.pct(r.te.recall) : "–") }, { label: "Test precision", align: "r", render: (r) => (r.te ? fmt.pct(r.te.precision) : "–") }] }),
      el("div", { class: "legend-note" }, "Differences between the tree models are within noise given the small number of fraud cases. Logistic regression uses class weights, which trades precision for recall."));
  });
  section(H.imp, () => api("/model/importance", { params: { top: 15 } }), (d) => {
    chartInto(H.imp, { type: "bar", ariaLabel: "Feature importance", data: { labels: d.features.map((f) => f.feature), datasets: [{ data: d.features.map((f) => f.mean_abs_shap), backgroundColor: COLORS.accent, borderRadius: 4 }] }, options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: axisOpts(), y: { grid: { display: false } } } } }, "chart-box tall");
    H.imp.append(el("div", { class: "legend-note" }, "V1–V28 are anonymised PCA components, so individual features cannot be mapped to real-world meanings."));
  });
  section(H.dist, () => api("/model/prediction-distribution"), (d) => {
    const entries = Object.entries(d.by_version); if (!entries.length) return clear(H.dist).append(emptyState("No predictions stored yet"));
    const pal = [COLORS.accent, COLORS.violet, COLORS.cyan, COLORS.med];
    chartInto(H.dist, { type: "bar", ariaLabel: "Prediction distribution", data: { labels: d.bins.slice(0, 20).map((b) => b.toFixed(2)), datasets: entries.map(([v, arr], i) => ({ label: v, data: arr, backgroundColor: pal[i % pal.length] })) }, options: { scales: { x: axisOpts(), y: { ...axisOpts(), type: "logarithmic", min: 0.8 } } } }, "chart-box tall");
  });
  section(H.hist, () => api("/model/history"), (d) => {
    clear(H.hist).append(dataTable({ rows: d.versions, columns: [{ key: "version", label: "Version", render: (r) => el("span", {}, r.version, " ", r.active ? el("span", { class: "badge ok" }, "active") : "") }, { label: "Created", render: (r) => fmt.datetime(r.created_at) }, { label: "Test PR-AUC", align: "r", render: (r) => fmt.pct(r.test_pr_auc) }, { label: "Recall", align: "r", render: (r) => fmt.pct(r.test_recall) }, { label: "Precision", align: "r", render: (r) => fmt.pct(r.test_precision) }, { label: "Threshold", align: "r", render: (r) => fmt.num(r.threshold, 3) }, { label: "Live predictions", align: "r", render: (r) => fmt.int(r.live_usage ? r.live_usage.predictions : 0) }] }),
      el("div", { class: "legend-note" }, "Train a new version with `python -m ml.train`; the newest becomes active (edit models/registry.json to roll back). Runs are also logged to MLflow."));
  });
  section(H.drift, () => api("/model/drift"), (d) => {
    if (d.status === "insufficient_data") return clear(H.drift).append(emptyState("Not enough data yet", `Needs ${d.min_required} scored transactions (have ${d.sample_size}).`));
    clear(H.drift).append(el("div", { style: "margin-bottom:8px" }, "Overall: ", statusBadge(d.status), el("span", { class: "faint" }, ` · sample ${fmt.int(d.sample_size)}`)),
      dataTable({ rows: d.indicators, columns: [{ key: "feature", label: "Feature" }, { label: "PSI", align: "r", render: (r) => r.psi.toFixed(3) }, { label: "", render: (r) => el("div", { class: "bar-inline" }, el("i", { style: `width:${Math.min(100, r.psi * 200)}%;background:${r.status === "stable" ? "var(--ok)" : r.status === "moderate_shift" ? "var(--warn)" : "var(--bad)"}` })) }, { label: "Status", render: (r) => statusBadge(r.status) }] }), el("div", { class: "legend-note" }, d.caveat));
  });
}
