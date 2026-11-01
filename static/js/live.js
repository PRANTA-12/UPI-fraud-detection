// Single shared WebSocket to /ws/live with exponential-backoff reconnect.
import { auth } from "./api.js";

export class LiveFeed {
  constructor() { this.state = "closed"; this.msgListeners = new Set(); this.stateListeners = new Set(); this.retry = 0; this.ws = null; this.timer = null; this.stopped = true; this.received = 0; }
  onMessage(fn) { this.msgListeners.add(fn); return () => this.msgListeners.delete(fn); }
  onState(fn) { this.stateListeners.add(fn); fn(this.state); return () => this.stateListeners.delete(fn); }
  _set(s) { this.state = s; this.stateListeners.forEach((f) => f(s)); }
  start() { this.stopped = false; this._connect(); }
  stop() { this.stopped = true; clearTimeout(this.timer); if (this.ws) this.ws.close(); this._set("closed"); }
  _connect() {
    if (this.stopped || !auth.token) return;
    this._set("connecting");
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/live?token=${encodeURIComponent(auth.token)}`);
    this.ws = ws;
    ws.onopen = () => { this.retry = 0; this._set("open"); };
    ws.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch { return; }
      if (m.type === "prediction") { this.received++; this.msgListeners.forEach((f) => f(m)); }
    };
    ws.onclose = () => {
      this._set("closed");
      if (this.stopped) return;
      const delay = Math.min(1000 * 2 ** this.retry++, 15000);
      this.timer = setTimeout(() => this._connect(), delay);
    };
    ws.onerror = () => ws.close();
  }
}
