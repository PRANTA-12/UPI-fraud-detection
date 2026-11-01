import { api } from "../api.js";
import { el, clear, panel, fmt, banner, toast, dataTable, section } from "../ui.js";

export async function mount(root, ctx) {
  const host = el("div", {});
  root.append(el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Settings"), el("p", {}, "Thresholds, refresh and alert preferences. Changes are validated server-side, apply to every user, and are written to the audit log."))), host);
  await section(host, () => api("/settings"), (data) => {
    const s = { ...data.settings }, ro = !data.can_edit, errs = {};
    const field = (key, label, type, help, attrs = {}) => {
      const input = el("input", { class: "input", id: `f-${key}`, type, value: s[key], disabled: ro, ...attrs, oninput: (e) => (s[key] = type === "number" ? Number(e.target.value) : e.target.value) });
      return el("div", { class: "field" }, el("label", { for: `f-${key}` }, label), input, help ? el("span", { class: "help" }, help) : null, el("span", { class: "err", id: `e-${key}` }));
    };
    const select = (key, label, opts, help) => el("div", { class: "field" }, el("label", { for: `f-${key}` }, label), el("select", { class: "input", id: `f-${key}`, disabled: ro, onchange: (e) => (s[key] = e.target.value) }, opts.map((o) => el("option", { value: o, selected: String(s[key]) === String(o) }, o))), help ? el("span", { class: "help" }, help) : null);
    const check = (key, label) => el("label", { class: "switch field" }, el("input", { type: "checkbox", checked: s[key], disabled: ro, onchange: (e) => (s[key] = e.target.checked) }), label);
    const msg = el("div", { class: "err", role: "alert" });
    const save = el("button", { class: "btn primary", disabled: ro, onclick: async () => {
      msg.textContent = ""; save.disabled = true;
      try { const r = await api("/settings", { method: "PUT", body: { ...s, risk_low_max: Number(s.risk_low_max), risk_high_min: Number(s.risk_high_min), refresh_seconds: Number(s.refresh_seconds), default_page_size: Number(s.default_page_size) } }); Object.assign(ctx.settings, r.settings); toast("Settings saved", "Applied for all users.", "ok"); }
      catch (e) { msg.textContent = e.message; } save.disabled = false;
    } }, "Save changes");
    clear(host).append(
      ro ? banner("You have read-only access. Only administrators can change settings.", "warn") : null,
      el("div", { class: "grid g-2" },
        panel("Risk classification", "Display bands applied to fraud probability", el("div", {}, field("risk_low_max", "Low → Medium boundary", "number", "Probabilities below this are Low (default 0.30)", { step: "0.01", min: "0.01", max: "0.99" }), field("risk_high_min", "Medium → High boundary", "number", "Probabilities at or above this are High (default 0.70)", { step: "0.01", min: "0.01", max: "0.99" }),
          el("div", { class: "legend-note" }, "The fraud/not-fraud decision threshold is part of the model version and cannot be edited here."))),
        panel("Dashboard", "", el("div", {}, field("refresh_seconds", "Refresh interval (seconds)", "number", "2–300. Applies on next page load.", { min: "2", max: "300" }), select("default_risk_filter", "Default live risk filter", ["All", "High", "Medium", "Low"]), select("default_page_size", "Default page size", [10, 25, 50, 100]))),
        panel("Alert preferences", "Toast notifications for flagged transactions", el("div", {}, check("alerts_enabled", "Enable fraud alert notifications"), select("alert_min_risk", "Notify from risk level", ["High", "Medium"], "Only flagged transactions at or above this level notify."), check("alert_sound", "Play sound (reserved)"))),
        panel("Model information", "Read-only", data.model ? el("dl", { class: "kv" }, ...[["Name", data.model.name], ["Version", data.model.version], ["Classification threshold", fmt.num(data.model.classification_threshold, 3)]].flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])) : el("span", { class: "muted" }, "No model loaded")),
        panel("Environment", "Non-sensitive only", el("div", {}, el("dl", { class: "kv" }, ...[["Mode", data.environment.app_env], ["Auth required", String(data.environment.auth_required)], ["WebSocket auth", String(data.environment.ws_require_auth)], ["Producer delay (ms)", data.environment.producer_delay_ms.join(" – ")]].flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)])), el("div", { class: "legend-note" }, data.protected)))),
      el("div", { class: "toolbar", style: "margin-top:14px" }, save, msg),
      data.can_edit ? el("div", {}, el("div", { class: "section-label" }, "Audit log (admin)"), panel("Recent administrative and security events", "", (() => { const h = el("div", {}); section(h, () => api("/admin/audit", { params: { page_size: 15 } }), (a) => clear(h).append(dataTable({ rows: a.items, empty: "No events", columns: [{ label: "Time", render: (r) => fmt.datetime(r.ts) }, { key: "username", label: "User" }, { key: "action", label: "Action" }, { key: "ip", label: "IP" }] }))); return h; })())) : null);
  });
}
