import { api } from "../api.js";
import { el, clear, panel, fmt, statusBadge, dataTable, kpi, banner, pollLoop, section } from "../ui.js";

export async function mount(root, ctx) {
  const host = el("div", {});
  root.append(el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "System Health Monitoring"), el("p", {}, "Live checks of the API, PostgreSQL, Redis, stream consumers and dead-letter queue. Only measured values are shown – no simulated CPU/RAM."))), host);
  const dot = (s) => el("span", { class: `dot ${s === "operational" || s === "up" ? "ok" : s === "degraded" || s === "idle" ? "warn" : "bad"}`, style: "margin-right:8px" });
  const card = (title, status, rows) => panel(el("span", {}, dot(status), title).textContent, "", el("div", {}, el("div", { style: "margin:-4px 0 8px" }, statusBadge(status)), el("dl", { class: "kv" }, rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v ?? "–")]))));
  const stop = pollLoop((signal) => section(host, () => api("/system/health", { signal }), (h) => {
    const c = h.components, lat = c.api.latency, ws = ctx.feed.state;
    clear(host).append(
      el("div", { class: `banner ${h.overall === "operational" ? "" : h.overall === "degraded" ? "warn" : "bad"}`, role: "status" }, el("b", {}, `Overall: ${h.overall}`), el("span", { class: "muted" }, ` · checked ${fmt.time(new Date(h.checked_at * 1000).toISOString())} · auto-refresh ${ctx.settings.refresh_seconds}s`)),
      el("div", { class: "grid g-3" },
        card("FastAPI", c.api.status, [["Requests (since start)", fmt.int(lat.total_requests)], ["Server errors", fmt.int(lat.server_errors)], ["Latency avg", fmt.ms(lat.avg_ms)], ["Latency p50 / p95", `${fmt.ms(lat.p50_ms)} / ${fmt.ms(lat.p95_ms)}`], ["Latency p99", fmt.ms(lat.p99_ms)], ["Uptime", lat.uptime_seconds ? `${Math.floor(lat.uptime_seconds / 60)} min` : "–"]]),
        card("PostgreSQL", c.postgresql.status, [["Query latency", fmt.ms(c.postgresql.latency_ms)], ["Stored predictions", fmt.int(h.throughput.total_predictions)]]),
        card("Redis", c.redis.status, [["Ping latency", fmt.ms(c.redis.latency_ms)], ["Stream length", fmt.int(h.stream.length)]]),
        card("Stream consumers", c.consumers.status, [["Live consumers", c.consumers.live], ["Processed (this run)", c.consumers.instances.map((i) => i.processed).join(", ") || "–"], ["Failed attempts", c.consumers.instances.map((i) => i.failed).join(", ") || "–"], ["Duplicates skipped", c.consumers.instances.map((i) => i.duplicates).join(", ") || "–"]]),
        card("Producer (replay)", c.producer.status, [["Instances", c.producer.instances.length], ["State", c.producer.instances.map((i) => i.state).join(", ") || "–"], ["Replay range", c.producer.instances.length ? (c.producer.instances[0].replay_from === "heldout" ? "held-out period only" : c.producer.instances[0].replay_from || "all") : "–"], ["Fraud sampling boost", c.producer.instances.length ? c.producer.instances[0].fraud_boost : "–"], ["Events sent", c.producer.instances.map((i) => i.sent).join(", ") || "–"]]),
        card("Dead-letter queue", c.dead_letter_queue.status, [["Messages", fmt.int(c.dead_letter_queue.size)], ["Meaning", "Messages that failed permanently or exhausted retries"]]),
        card("WebSocket", c.websocket.status, [["Server connections", fmt.int(c.websocket.connections)], ["Messages broadcast", fmt.int(c.websocket.messages_sent)], ["This browser", ws === "open" ? "connected" : ws]]),
        card("Model", c.model.status, [["Active version", c.model.active_version]]),
        card("Throughput", "operational", [["Predictions, last 60 s", fmt.int(h.throughput.predictions_last_60s)], ["Rate", `${fmt.num(h.throughput.tps_60s, 2)} /s`], ["Stream-sourced total", fmt.int(h.throughput.stream_predictions)]])),
      el("div", { class: "section-label" }, "Consumer groups"),
      panel("Redis stream", `${h.stream.name}`, dataTable({ empty: "No consumer group yet – start the consumer", rows: h.stream.groups, columns: [{ key: "name", label: "Group" }, { key: "consumers", label: "Consumers", align: "r" }, { key: "pending", label: "Pending", align: "r" }, { key: "lag", label: "Lag", align: "r" }, { key: "last_delivered_id", label: "Last delivered", render: (r) => el("span", { class: "mono" }, r.last_delivered_id) }] })),
      el("div", { style: "height:14px" }),
      panel("Recent dead-lettered messages", "Newest 5", dataTable({ empty: "Dead-letter queue is empty", rows: c.dead_letter_queue.recent, columns: [{ label: "Original ID", render: (r) => el("span", { class: "mono" }, r.original_id) }, { key: "error", label: "Error" }, { key: "deliveries", label: "Deliveries", align: "r" }, { label: "Failed at", render: (r) => fmt.datetime(r.failed_at) }] })),
      el("div", { class: "legend-note" }, h.disclaimer));
  }, { skeletonHeight: 260, silent: !!host.childElementCount }), ctx.settings.refresh_seconds);
  return stop;
}
