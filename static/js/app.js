import { api, auth, ApiError } from "./api.js";
import { LiveFeed } from "./live.js";
import { el, clear, icon, toast, destroyCharts, fmt } from "./ui.js";
import * as overview from "./pages/overview.js";
import * as live from "./pages/live.js";
import * as analytics from "./pages/analytics.js";
import * as investigate from "./pages/investigate.js";
import * as model from "./pages/model.js";
import * as system from "./pages/system.js";
import * as settingsPage from "./pages/settings.js";

const ROUTES = [
  { path: "overview", label: "Executive Overview", icon: "overview", page: overview },
  { path: "live", label: "Live Monitoring", icon: "live", page: live },
  { path: "analytics", label: "Fraud Analytics", icon: "analytics", page: analytics },
  { path: "investigate", label: "Investigation Center", icon: "search", page: investigate },
  { path: "model", label: "AI Model Intelligence", icon: "model", page: model },
  { path: "system", label: "System Health", icon: "system", page: system },
  { path: "settings", label: "Settings", icon: "settings", page: settingsPage },
];

export const ctx = { settings: null, can_edit: false, feed: new LiveFeed(), navigate: (p) => { location.hash = `#/${p}`; } };
let cleanup = null, alertUnsub = null, rootEl;

function parseHash() {
  const [path, ...rest] = (location.hash.replace(/^#\/?/, "") || "overview").split("/");
  return { path: ROUTES.some((r) => r.path === path) ? path : "overview", params: rest };
}

async function loadSettings() {
  const s = await api("/settings");
  ctx.settings = s.settings; ctx.can_edit = s.can_edit; ctx.activeVersion = s.model ? s.model.version : null; ctx.modelInfo = s.model; ctx.environment = s.environment;
}

function renderLogin(message) {
  ctx.feed.stop(); clear(rootEl);
  const err = el("div", { class: "err", role: "alert" }, message || "");
  const user = el("input", { class: "input", id: "u", autocomplete: "username", required: true });
  const pass = el("input", { class: "input", id: "p", type: "password", autocomplete: "current-password", required: true });
  const btn = el("button", { class: "btn primary", type: "submit", style: "justify-content:center" }, "Sign in");
  const form = el("form", { onsubmit: async (e) => {
    e.preventDefault(); btn.disabled = true; err.textContent = "";
    try {
      const t = await api("/auth/login", { method: "POST", body: { username: user.value, password: pass.value } });
      auth.set(t.access_token, { username: t.username, role: t.role }); await boot();
    } catch (x) { err.textContent = x instanceof ApiError && x.status === 429 ? "Too many attempts. Wait a minute." : x.message; btn.disabled = false; }
  } },
    el("div", { class: "field" }, el("label", { for: "u" }, "Username"), user),
    el("div", { class: "field" }, el("label", { for: "p" }, "Password"), pass), err, btn);
  rootEl.append(el("div", { class: "login" }, el("div", { class: "panel" },
    el("div", { class: "brand", style: "margin-bottom:16px" }, el("div", { class: "brand-mark" }, icon("shield", 18)), el("div", {}, el("b", {}, "UPI SENTINEL"), el("small", {}, "FRAUD INTELLIGENCE PLATFORM"))),
    el("h1", { style: "margin-bottom:4px" }, "Sign in"), el("p", { class: "muted", style: "margin:0 0 16px" }, "Authorised analysts only."), form)));
  user.focus();
}

function shell() {
  clear(rootEl);
  const nav = el("nav", { class: "nav", "aria-label": "Main" }, ROUTES.map((r) => el("a", { href: `#/${r.path}`, dataset: { route: r.path }, onclick: () => sidebar.classList.remove("open") }, icon(r.icon), r.label)));
  const u = auth.user || {};
  const sidebar = el("aside", { class: "sidebar" },
    el("div", { class: "brand" }, el("div", { class: "brand-mark" }, icon("shield", 18)), el("div", {}, el("b", {}, "SENTINEL"), el("small", {}, "FRAUD INTELLIGENCE"))), nav,
    el("div", { class: "side-foot" }, el("div", {}, el("b", {}, u.username || ""), " · ", u.role || ""),
      el("button", { class: "btn sm", style: "margin-top:8px", onclick: () => { auth.clear(); renderLogin(); } }, "Sign out")));
  const dot = el("span", { class: "dot" }), connText = el("span", {}, "Connecting");
  const title = el("h1", { id: "page-title" });
  const topbar = el("header", { class: "topbar" },
    el("button", { class: "menu-btn", "aria-label": "Open menu", onclick: () => sidebar.classList.toggle("open") }, icon("menu", 18)),
    title, el("div", { class: "spacer" }),
    el("div", { class: "conn", title: "Live WebSocket feed" }, dot, connText));
  const view = el("main", { class: "content", id: "view", tabindex: "-1" });
  rootEl.append(el("div", { class: "shell" }, sidebar, el("div", { class: "main" }, topbar, view)));
  ctx.feed.onState((s) => {
    dot.className = `dot ${s === "open" ? "ok" : s === "connecting" ? "warn" : "bad"}`;
    connText.textContent = s === "open" ? "Live" : s === "connecting" ? "Connecting…" : "Disconnected";
  });
  return { view, title, nav };
}

function setupAlerts() {
  alertUnsub && alertUnsub();
  alertUnsub = ctx.feed.onMessage((m) => {
    const s = ctx.settings; if (!s || !s.alerts_enabled || !m.alert) return;
    if (s.alert_min_risk === "High" && m.risk_level !== "High") return;
    toast(`Fraud alert · TXN ${m.transaction_id}`, `${m.risk_level} risk · p=${fmt.prob(m.fraud_probability)} · amount ${fmt.money(m.amount)}`, "alert", () => { location.hash = `#/investigate/${m.transaction_id}`; });
  });
}

let ui;
async function render() {
  if (!auth.token || !ui) return;
  const { path, params } = parseHash();
  const route = ROUTES.find((r) => r.path === path);
  cleanup && cleanup(); cleanup = null; destroyCharts(ui.view); clear(ui.view);
  ui.nav.querySelectorAll("a").forEach((a) => (a.dataset.route === path ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  ui.title.textContent = route.label; document.title = `${route.label} · UPI SENTINEL`;
  try { cleanup = (await route.page.mount(ui.view, { ...ctx, params })) || null; }
  catch (e) { if (e.name !== "AbortError") console.error(e); }
}

async function boot() {
  try { await loadSettings(); } catch (e) { return renderLogin(e.status === 401 ? "" : e.message); }
  ui = shell(); setupAlerts(); ctx.feed.start(); await render();
}

auth.onUnauthorized(() => renderLogin("Session expired. Please sign in again."));
window.addEventListener("hashchange", render);
rootEl = document.getElementById("root");
if (auth.token) boot(); else renderLogin();
