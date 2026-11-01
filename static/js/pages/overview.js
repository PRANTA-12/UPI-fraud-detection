import { api } from "../api.js";
import { el, clear, kpi, kpiSkeletons, panel, chartInto, COLORS, axisOpts, fmt, riskBadge, classTag, dataTable, emptyState, statusBadge, banner, pollLoop, section, skeleton } from "../ui.js";

export async function mount(root, ctx) {
  const kpiHost = el("div", { class: "grid g-kpi" }, kpiSkeletons(9));
  const mk = () => el("div", {});
  const volume = mk(), trend = mk(), donut = mk(), risk = mk(), table = mk(), status = mk();
  root.append(
    el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Executive Overview"), el("p", {}, "Operational and risk summary computed from PostgreSQL aggregates and measured runtime data."))),
    banner("Dataset note: scores come from a model trained on the public Credit Card Fraud dataset (anonymised features), used here as a UPI-style prototype. “Predicted” figures are model outputs; “Ground truth” figures use replayed dataset labels. Only the “Held-out” figures are an honest performance estimate – other ground-truth figures can include transactions the model trained on."),
    el("div", { class: "section-label" }, "Model predictions"), kpiHost,
    el("div", { class: "section-label" }, "Trends (prediction processing time)"),
    el("div", { class: "grid g-2" }, panel("Transaction volume", "Scoring events per minute · last 2 h", volume), panel("Fraud detection trend", "Flagged by model vs actual fraud labels", trend)),
    el("div", { class: "section-label" }, "Distribution"),
    el("div", { class: "grid g-2" }, panel("Predicted fraud vs legitimate", "Latest prediction per transaction", donut), panel("Risk distribution", "Current risk bands", risk)),
    el("div", { class: "section-label" }, "Attention"),
    el("div", { class: "grid g-main" }, panel("Recent suspicious transactions", "Flagged or high-risk · click to investigate", table), panel("System status", "Live from /system/health", status)));

  const loadKpis = async (signal) => {
    const k = await api("/dashboard/kpis", { params: { model_version: ctx.activeVersion }, signal });
    const p = k.predicted, g = k.ground_truth, perf = k.performance;
    clear(kpiHost).append(
      kpi({ label: "Transactions processed", value: fmt.int(p.processed), hint: `of ${fmt.int(k.scope.transactions_in_database)} in database`, cls: "accent-pred" }),
      kpi({ label: "Predicted legitimate", value: fmt.int(p.legitimate), cls: "accent-pred" }),
      kpi({ label: "Flagged (predicted fraud)", value: fmt.int(p.flagged), hint: `${fmt.pct(p.flagged_rate)} of processed`, cls: "accent-pred" }),
      kpi({ label: "High-risk (≥ band)", value: fmt.int(p.high_risk), cls: "accent-pred" }),
      kpi({ label: "Fraud detection rate (all processed)", value: fmt.pct(g.detection_rate), hint: `caught ${g.caught} of ${g.actual_fraud_processed} · may include training data`, cls: "accent-truth" }),
      kpi({ label: "Held-out detection rate", value: g.held_out.actual_fraud ? fmt.pct(g.held_out.detection_rate) : "n/a", hint: g.held_out.processed ? `${g.held_out.caught} of ${g.held_out.actual_fraud} fraud · ${fmt.int(g.held_out.processed)} unseen txns` : "no unseen transactions scored yet", cls: "accent-truth" }),
      kpi({ label: "Held-out precision", value: g.held_out.precision === null ? "n/a" : fmt.pct(g.held_out.precision), hint: `${g.held_out.false_alarms} false alarms · ${g.held_out.missed} missed`, cls: "accent-truth" }),
      kpi({ label: "Total amount processed", value: fmt.money(k.amounts.total), hint: `${fmt.money(k.amounts.flagged)} flagged · dataset units`, cls: "accent-ops" }),
      kpi({ label: "Avg latency · throughput", value: `${fmt.ms(perf.avg_latency_ms_15m)}`, hint: `${fmt.num(perf.throughput_tps_60s, 2)} txn/s (60 s) · p95 ${fmt.ms(perf.p95_latency_ms_15m)}`, cls: "accent-ops" }));
    return k;
  };
  const loadCharts = async (signal) => {
    const [t, r, k] = await Promise.all([api("/dashboard/trends", { params: { bucket: "minute", window_hours: 2 }, signal }), api("/dashboard/risk-distribution", { params: { model_version: ctx.activeVersion }, signal }), api("/dashboard/kpis", { params: { model_version: ctx.activeVersion }, signal })]);
    const labels = t.points.map((x) => fmt.time(x.bucket));
    if (!t.points.length) { clear(volume).append(emptyState("No scoring events yet", "Start the producer and consumer to see traffic.")); clear(trend).append(emptyState("No data yet")); }
    else {
      chartInto(volume, { type: "line", ariaLabel: "Scoring events per minute", data: { labels, datasets: [{ label: "Events / min", data: t.points.map((x) => x.events), borderColor: COLORS.accent, backgroundColor: "rgba(79,140,255,.15)", fill: true, tension: .3, pointRadius: 0 }] }, options: { scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }) }, plugins: { legend: { display: false } } } });
      chartInto(trend, { type: "bar", ariaLabel: "Flagged vs actual fraud per minute", data: { labels, datasets: [{ label: "Flagged by model", data: t.points.map((x) => x.flagged), backgroundColor: COLORS.high }, { label: "Actual fraud (label)", data: t.points.map((x) => x.actual_fraud), backgroundColor: COLORS.violet }] }, options: { scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }) } } });
    }
    const p = k.predicted;
    if (!p.processed) clear(donut).append(emptyState("Nothing scored yet"));
    else chartInto(donut, { type: "doughnut", ariaLabel: "Predicted fraud vs legitimate", data: { labels: ["Legitimate", "Flagged"], datasets: [{ data: [p.legitimate, p.flagged], backgroundColor: [COLORS.low, COLORS.high], borderWidth: 0 }] }, options: { cutout: "68%", plugins: { legend: { position: "bottom" } } } });
    chartInto(risk, { type: "bar", ariaLabel: "Risk distribution", data: { labels: r.distribution.map((d) => d.risk), datasets: [{ data: r.distribution.map((d) => d.count), backgroundColor: [COLORS.low, COLORS.med, COLORS.high], borderRadius: 6 }] }, options: { scales: { x: axisOpts(), y: axisOpts({ beginAtZero: true }) }, plugins: { legend: { display: false } } } });
  };
  const loadTable = async (signal) => {
    const d = await api("/dashboard/recent-suspicious", { params: { limit: 8 }, signal });
    clear(table).append(dataTable({ empty: "No suspicious transactions yet", rows: d.items, onRowClick: (r) => ctx.navigate(`investigate/${r.transaction_id}`),
      columns: [{ key: "transaction_id", label: "Txn ID" }, { key: "amount", label: "Amount", align: "r", render: (r) => fmt.money(r.amount) }, { key: "fraud_probability", label: "Probability", align: "r", render: (r) => fmt.prob(r.fraud_probability) }, { label: "Risk", render: (r) => riskBadge(r.risk_level) }, { label: "Actual", render: (r) => classTag(r.actual_class, "actual") }, { label: "Processed", render: (r) => fmt.time(r.processed_at) }] }));
  };
  const loadStatus = async (signal) => {
    const h = await api("/system/health", { signal }); const c = h.components;
    const row = (n, s, extra) => el("div", { style: "display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--border)" }, el("span", {}, n, extra ? el("span", { class: "faint" }, ` · ${extra}`) : null), statusBadge(s));
    clear(status).append(el("div", { style: "margin-bottom:8px" }, "Overall: ", statusBadge(h.overall)),
      row("API", c.api.status, c.api.latency.p95_ms ? `p95 ${fmt.ms(c.api.latency.p95_ms)}` : ""), row("PostgreSQL", c.postgresql.status), row("Redis", c.redis.status),
      row("Consumers", c.consumers.status, `${c.consumers.live} live`), row("Dead-letter queue", c.dead_letter_queue.status, `${c.dead_letter_queue.size ?? 0} msgs`), row("Model", c.model.status, c.model.active_version));
  };
  const stops = [
    pollLoop(async (s) => { await Promise.all([section(kpiHost, () => loadKpis(s), () => {}, { silent: true }), section(volume, () => loadCharts(s), () => {}, { silent: true }), section(table, () => loadTable(s), () => {}, { silent: true }), section(status, () => loadStatus(s), () => {}, { silent: true })]); }, ctx.settings.refresh_seconds)];
  return () => stops.forEach((f) => f());
}
