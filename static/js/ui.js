// Reusable UI building blocks. All dynamic text is inserted with textContent (no innerHTML on data) => XSS-safe.
const SVG_NS = "http://www.w3.org/2000/svg";

export const ICONS = {
  overview: "M3 13h8V3H3zm10 8h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z",
  live: "M2 12h4l3-8 4 16 3-8h6",
  analytics: "M4 20V10m6 10V4m6 16v-7m6 7H2",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zm10 2-4.3-4.3",
  model: "M12 2a4 4 0 0 0-4 4v1a4 4 0 0 0-3 6 4 4 0 0 0 3 6v0a4 4 0 0 0 8 0v0a4 4 0 0 0 3-6 4 4 0 0 0-3-6V6a4 4 0 0 0-4-4zm0 0v20",
  system: "M3 5h18v6H3zm0 8h18v6H3zM7 8h.01M7 16h.01",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2-1.2L14.5 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.3-.9-2 3.4 2 1.5a7 7 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2 1.2l.5 2.6h4l.5-2.6a7 7 0 0 0 2-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z",
  shield: "M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5z",
  alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2m20 0-3.5-7.5A2 2 0 0 0 16.7 3H7.3a2 2 0 0 0-1.8 1.5L2 12m20 0v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6",
  menu: "M3 6h18M3 12h18M3 18h18",
  pause: "M6 4h4v16H6zM14 4h4v16h-4z", play: "M6 4l14 8-14 8z",
};

export function icon(name, size) {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor");
  s.setAttribute("stroke-width", "1.8"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
  s.setAttribute("aria-hidden", "true");
  if (size) { s.setAttribute("width", size); s.setAttribute("height", size); }
  const p = document.createElementNS(SVG_NS, "path"); p.setAttribute("d", ICONS[name] || ""); s.appendChild(p);
  return s;
}

export function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === "class") n.className = v;
    else if (k === "dataset") Object.assign(n.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v === true) n.setAttribute(k, "");
    else n.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    n.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return n;
}

export const clear = (n) => { while (n.firstChild) n.removeChild(n.firstChild); return n; };

/* ---------- formatting ---------- */
const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const nf2 = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const fmt = {
  int: (v) => (v === null || v === undefined ? "–" : nf0.format(v)),
  num: (v, d = 2) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })),
  money: (v) => (v === null || v === undefined ? "–" : nf2.format(v)),
  pct: (v, d = 1) => (v === null || v === undefined ? "–" : `${(v * 100).toFixed(d)}%`),
  prob: (v) => (v === null || v === undefined ? "–" : v >= 0.0001 ? v.toFixed(4) : v.toExponential(1)),
  ms: (v) => (v === null || v === undefined ? "–" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Number(v).toFixed(v < 10 ? 1 : 0)} ms`),
  time: (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour12: false }) : "–"),
  datetime: (iso) => (iso ? new Date(iso).toLocaleString([], { hour12: false }) : "–"),
  compact: (v) => (v === null || v === undefined ? "–" : Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v)),
};

/* ---------- small components ---------- */
export const riskBadge = (level) => el("span", { class: `badge ${String(level || "").toLowerCase()}` }, level || "–");
export const statusBadge = (status) => {
  const map = { operational: ["ok", "Operational"], up: ["ok", "Up"], degraded: ["warn", "Degraded"], down: ["bad", "Down"], idle: ["neutral", "Idle"], completed: ["ok", "Completed"], failed: ["bad", "Failed"], stable: ["ok", "Stable"], moderate_shift: ["warn", "Moderate shift"], significant_shift: ["bad", "Significant shift"], insufficient_data: ["neutral", "Insufficient data"] };
  const [cls, label] = map[status] || ["neutral", status || "–"];
  return el("span", { class: `badge ${cls}` }, label);
};
export const classTag = (v, kind = "pred") =>
  v === null || v === undefined ? el("span", { class: "faint" }, "–")
    : el("span", { class: `tag ${v === 1 ? "fraud" : "legit"}` }, v === 1 ? (kind === "pred" ? "Flagged" : "Fraud") : (kind === "pred" ? "Clear" : "Legit"));

export function kpi({ label, value, hint, cls = "" }) {
  return el("div", { class: `kpi ${cls}` }, el("div", { class: "label" }, label), el("div", { class: "value" }, value), hint ? el("div", { class: "hint" }, hint) : null);
}
export function kpiSkeletons(n = 8) {
  return Array.from({ length: n }, () => el("div", { class: "kpi" }, el("div", { class: "skeleton", style: "height:12px;width:60%" }), el("div", { class: "skeleton", style: "height:24px;width:40%;margin-top:10px" })));
}
export const skeleton = (h = 120) => el("div", { class: "skeleton", style: `height:${h}px` });
export const emptyState = (title, hint) => el("div", { class: "empty" }, icon("inbox"), el("b", {}, title), hint ? el("span", { class: "faint" }, hint) : null);
export function errorState(err, retry) {
  return el("div", { class: "error-state", role: "alert" }, icon("alert"), el("b", {}, "Could not load this section"),
    el("span", {}, err && err.message ? err.message : String(err)), retry ? el("button", { class: "btn sm", onclick: retry }, "Retry") : null);
}
export const banner = (text, kind = "") => el("div", { class: `banner ${kind}`, role: "note" }, icon("shield", 16), el("div", {}, text));

export function panel(title, sub, body, actions) {
  return el("section", { class: "panel" },
    el("div", { class: "panel-head" }, el("div", {}, el("h2", {}, title), sub ? el("div", { class: "sub" }, sub) : null), actions || null), body);
}

/** columns: [{key,label,render?,align?,sortable?}] */
export function dataTable({ columns, rows, onRowClick, empty = "No data", sort, onSort, rowClass }) {
  if (!rows || !rows.length) return emptyState(empty);
  const head = el("tr", {}, columns.map((c) => {
    const active = sort && sort.key === c.key;
    return el("th", { class: `${c.align === "r" ? "r" : ""} ${c.sortable ? "sortable" : ""}`, "aria-sort": active ? (sort.order === "asc" ? "ascending" : "descending") : null,
      onclick: c.sortable && onSort ? () => onSort(c.key) : null }, c.label, active ? (sort.order === "asc" ? " ▲" : " ▼") : "");
  }));
  const body = rows.map((r) => {
    const tr = el("tr", { class: `${onRowClick ? "clickable" : ""} ${rowClass ? rowClass(r) : ""}`, tabindex: onRowClick ? "0" : null,
      onclick: onRowClick ? () => onRowClick(r, tr) : null,
      onkeydown: onRowClick ? (e) => { if (e.key === "Enter") onRowClick(r, tr); } : null },
      columns.map((c) => el("td", { class: c.align === "r" ? "r num" : "" }, c.render ? c.render(r) : r[c.key] ?? "–")));
    return tr;
  });
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
}

export function pager({ page, totalPages, total, onPage }) {
  return el("div", { class: "pager" }, el("span", {}, `${fmt.int(total)} result${total === 1 ? "" : "s"} · page ${page} of ${totalPages}`),
    el("div", { class: "toolbar" },
      el("button", { class: "btn sm", disabled: page <= 1, onclick: () => onPage(page - 1) }, "← Prev"),
      el("button", { class: "btn sm", disabled: page >= totalPages, onclick: () => onPage(page + 1) }, "Next →")));
}

/* ---------- toasts ---------- */
export function toast(title, body, kind = "info", onClick, ms = 6000) {
  const host = document.getElementById("toasts"); if (!host) return;
  const t = el("div", { class: `toast ${kind}`, role: kind === "alert" ? "alert" : "status", onclick: () => { t.remove(); onClick && onClick(); } },
    el("b", {}, title), body ? el("div", { class: "muted", style: "font-size:12.5px" }, body) : null);
  host.append(t); while (host.children.length > 4) host.firstChild.remove();
  setTimeout(() => t.remove(), ms);
}

/* ---------- charts (Chart.js, themed) ---------- */
export const COLORS = { accent: "#4f8cff", violet: "#a78bfa", cyan: "#22d3ee", low: "#34d399", med: "#fbbf24", high: "#f87171", grid: "rgba(148,163,184,.12)", text: "#a3b0c8" };
let themed = false;
function theme() {
  if (themed || !window.Chart) return; themed = true;
  const C = window.Chart; C.defaults.color = COLORS.text; C.defaults.font.family = getComputedStyle(document.body).fontFamily;
  C.defaults.font.size = 11.5; C.defaults.borderColor = COLORS.grid; C.defaults.animation = { duration: 250 };
  C.defaults.maintainAspectRatio = false; C.defaults.plugins.legend.labels.boxWidth = 10;
  C.defaults.plugins.legend.labels.usePointStyle = true;
  C.defaults.plugins.tooltip.backgroundColor = "#0b1328"; C.defaults.plugins.tooltip.borderColor = "rgba(148,163,184,.3)";
  C.defaults.plugins.tooltip.borderWidth = 1; C.defaults.plugins.tooltip.padding = 10;
}
/** Creates (or updates in place) a chart inside `host`. Returns {update(config)}. */
export function chartInto(host, config, height = "chart-box") {
  theme();
  if (!window.Chart) { clear(host).append(errorState(new Error("Chart library failed to load"))); return null; }
  let canvas = host.querySelector("canvas");
  if (host._chart && canvas) { host._chart.data = config.data; if (config.options) host._chart.options = config.options; host._chart.update(); return host._chart; }
  clear(host); const box = el("div", { class: height }); canvas = el("canvas", { role: "img", "aria-label": config.ariaLabel || "chart" }); box.append(canvas); host.append(box);
  host._chart = new window.Chart(canvas.getContext("2d"), config);
  return host._chart;
}
export function destroyCharts(root) { root.querySelectorAll("*").forEach((n) => { if (n._chart) { n._chart.destroy(); n._chart = null; } }); }
export const axisOpts = (extra = {}) => ({ grid: { color: COLORS.grid }, ticks: { maxTicksLimit: 8 }, ...extra });

/** Runs fn now and every `seconds`, never overlapping; returns stop(). fn receives an AbortSignal. */
export function pollLoop(fn, seconds) {
  let stopped = false, timer = null, ctl = null, running = false;
  const tick = async () => {
    if (stopped || running) return; running = true; ctl = new AbortController();
    try { await fn(ctl.signal); } catch (e) { if (e.name !== "AbortError") console.error(e); }
    running = false; if (!stopped) timer = setTimeout(tick, seconds * 1000);
  };
  tick();
  return () => { stopped = true; clearTimeout(timer); ctl && ctl.abort(); };
}
/** Fill `host` with skeleton, run loader, render result or error state (with retry). */
export async function section(host, loader, render, { skeletonHeight = 200, silent = false } = {}) {
  if (!silent && !host.childElementCount) host.append(skeleton(skeletonHeight));
  try { const data = await loader(); render(data, host); }
  catch (e) { if (e.name === "AbortError") return; clear(host); host.append(errorState(e, () => section(host, loader, render, { skeletonHeight }))); }
}
