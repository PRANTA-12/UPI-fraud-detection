// REST client: bearer token in sessionStorage (cleared on tab close), uniform errors, 401 -> login.
const TOKEN_KEY = "sentinel.token", USER_KEY = "sentinel.user";
let onUnauthorized = () => {};

export const auth = {
  get token() { return sessionStorage.getItem(TOKEN_KEY); },
  get user() { try { return JSON.parse(sessionStorage.getItem(USER_KEY)); } catch { return null; } },
  set(token, user) { sessionStorage.setItem(TOKEN_KEY, token); sessionStorage.setItem(USER_KEY, JSON.stringify(user)); },
  clear() { sessionStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(USER_KEY); },
  onUnauthorized(fn) { onUnauthorized = fn; },
};

export class ApiError extends Error {
  constructor(status, message, body) { super(message); this.status = status; this.body = body; }
}

export async function api(path, { method = "GET", body, params, signal } = {}) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  let res;
  try { res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, signal }); }
  catch (e) { if (e.name === "AbortError") throw e; throw new ApiError(0, "Cannot reach the API. Check that the server is running."); }
  const data = await res.json().catch(() => null);
  if (res.status === 401 && path !== "/auth/login") { auth.clear(); onUnauthorized(); }
  if (!res.ok) {
    let msg = data && data.detail ? data.detail : res.statusText;
    if (Array.isArray(msg)) msg = msg.map((m) => `${(m.loc || []).slice(1).join(".")}: ${m.msg}`).join("; ");
    throw new ApiError(res.status, msg, data);
  }
  return data;
}
