import { api } from "../api.js";
import { el, clear, icon, riskBadge, classTag, fmt, dataTable, emptyState, panel, kpi } from "../ui.js";

const MAX_ROWS = 150;

export async function mount(root, ctx) {
  let paused = false, buffered = [], rows = [], risk = ctx.settings.default_risk_filter || "All", query = "", selected = null, perfWindow = [];
  const tableHost = el("div", {}), statHost = el("div", { class: "grid g-kpi", style: "margin-bottom:14px" }), drawer = el("aside", { class: "drawer", "aria-label": "Transaction detail" });
  const pauseBtn = el("button", { class: "btn", onclick: () => setPaused(!paused) });
  const bufInfo = el("span", { class: "muted" });
  const search = el("input", { class: "input", placeholder: "Search transaction ID", inputmode: "numeric", "aria-label": "Search by transaction ID", oninput: (e) => { query = e.target.value.trim().replace(/\D/g, ""); draw(); } });
  const seg = el("div", { class: "seg", role: "group", "aria-label": "Risk filter" }, ["All", "High", "Medium", "Low"].map((r) => el("button", { "aria-pressed": String(r === risk), onclick: (e) => { risk = r; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); draw(); } }, r)));

  function setPaused(p) {
    paused = p; clear(pauseBtn).append(icon(p ? "play" : "pause", 14), p ? " Resume" : " Pause");
    if (!p && buffered.length) { rows = [...buffered.reverse(), ...rows].slice(0, MAX_ROWS); buffered = []; draw(); }
    bufInfo.textContent = p ? "Feed paused – new events are buffered" : "";
  }
  setPaused(false);

  const matches = (r) => (risk === "All" || r.risk_level === risk) && (!query || String(r.transaction_id).startsWith(query));
  function draw() {
    const view = rows.filter(matches);
    clear(tableHost).append(dataTable({ empty: ctx.feed.state === "open" ? "Waiting for transactions…" : "Not connected to the live feed", rows: view.slice(0, 100),
      rowClass: (r) => `${r.alert ? "alert-row" : ""} ${r._new ? "flash" : ""} ${selected && selected.transaction_id === r.transaction_id ? "selected" : ""}`,
      onRowClick: (r) => open(r),
      columns: [{ key: "transaction_id", label: "Txn ID" }, { key: "amount", label: "Amount", align: "r", render: (r) => fmt.money(r.amount) }, { key: "fraud_probability", label: "Fraud probability", align: "r", render: (r) => fmt.prob(r.fraud_probability) },
        { label: "Risk", render: (r) => riskBadge(r.risk_level) }, { label: "Prediction", render: (r) => classTag(r.predicted_class) }, { label: "Processed", render: (r) => fmt.time(r.processed_at) },
        { label: "Latency", align: "r", render: (r) => fmt.ms(r.latency_ms) }, { label: "Status", render: (r) => el("span", { class: "tag" }, r.status || "completed") }] }));
    rows.forEach((r) => (r._new = false));
  }
  function open(r) {
    selected = r; clear(drawer).append(
      el("div", { class: "panel-head" }, el("h2", {}, `Transaction ${r.transaction_id}`), el("button", { class: "btn sm", onclick: close, "aria-label": "Close" }, "✕")),
      el("div", { style: "display:flex;gap:8px;margin-bottom:12px" }, riskBadge(r.risk_level), classTag(r.predicted_class)),
      el("dl", { class: "kv" }, ...[["Amount", fmt.money(r.amount)], ["Fraud probability", fmt.prob(r.fraud_probability)], ["Decision threshold", fmt.num(r.threshold, 3)], ["Model", `${r.model_name || ""} ${r.model_version || ""}`], ["Source", r.source], ["Processed", fmt.datetime(r.processed_at)],
        ["End-to-end latency", fmt.ms(r.latency_ms)], ["Inference time", fmt.ms(r.inference_ms)], ["Status", r.status], ["Actual label (replay)", r.actual_class === null || r.actual_class === undefined ? "n/a" : r.actual_class ? "Fraud" : "Legitimate"]].flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v ?? "–")])),
      el("div", { style: "margin-top:16px;display:flex;gap:8px" }, el("button", { class: "btn primary", onclick: () => ctx.navigate(`investigate/${r.transaction_id}`) }, "Open in Investigation Center")));
    drawer.classList.add("open"); draw();
  }
  function close() { selected = null; drawer.classList.remove("open"); draw(); }

  const unsub = ctx.feed.onMessage((m) => {
    perfWindow.push(Date.now()); m._new = true;
    if (paused) { buffered.push(m); if (buffered.length > 500) buffered.shift(); bufInfo.textContent = `Feed paused – ${buffered.length} buffered`; return; }
    rows.unshift(m); if (rows.length > MAX_ROWS) rows.pop(); draw();
  });
  const unsubState = ctx.feed.onState(() => draw());
  const statTimer = setInterval(() => {
    const now = Date.now(); perfWindow = perfWindow.filter((t) => now - t < 10000);
    const live = rows.slice(0, 50); const flagged = live.filter((r) => r.predicted_class === 1).length;
    clear(statHost).append(kpi({ label: "Events / s (last 10 s, this browser)", value: fmt.num(perfWindow.length / 10, 1) }), kpi({ label: "Feed connection", value: ctx.feed.state === "open" ? "Live" : ctx.feed.state }),
      kpi({ label: "Flagged in last 50 events", value: `${flagged}`, hint: "Replay may over-sample fraud for demos" }), kpi({ label: "Rows in view", value: String(rows.length), hint: `kept: latest ${MAX_ROWS}` }));
  }, 1000);

  root.append(el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Live Transaction Monitoring"), el("p", {}, "Predictions stream in over WebSocket as the consumer scores them. Red rows were flagged as fraud."))),
    statHost, panel("Transaction feed", "Newest first · click a row for details", tableHost,
      el("div", { class: "toolbar" }, bufInfo, search, seg, pauseBtn)), drawer);
  draw();
  // seed with recent real predictions so the page is not empty after load
  try {
    const seed = await api("/transactions", { params: { page_size: 25, sort: "processed_at", order: "desc" } });
    if (!rows.length) { rows = seed.items.map((r) => ({ ...r, model_name: undefined })); draw(); }
  } catch (e) { /* feed still works */ }
  return () => { unsub(); unsubState(); clearInterval(statTimer); };
}
