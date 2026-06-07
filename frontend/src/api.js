// api.js — thin fetch wrapper. Cookies travel automatically (same-origin via proxy).

async function request(method, path, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
    credentials: "include",
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`/api${path}`, opts);
  if (res.status === 204) return null;
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || res.statusText;
    const err = new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b),
  patch: (p, b) => request("PATCH", p, b),
  del: (p) => request("DELETE", p),
};

export const auth = {
  config: () => api.get("/auth/config"),
  me: () => api.get("/auth/me"),
  devLogin: (email) => api.post(`/auth/dev-login?email=${encodeURIComponent(email)}`),
  logout: () => api.post("/auth/logout"),
  googleLoginUrl: "/api/auth/google/login",
};

export const accounts = {
  list: () => api.get("/accounts"),
  create: (a) => api.post("/accounts", a),
  createDemo: (type) => api.post(`/accounts/demo?account_type=${type}`),
  update: (id, a) => api.patch(`/accounts/${id}`, a),
  remove: (id) => api.del(`/accounts/${id}`),
  activate: (id) => api.post(`/accounts/${id}/activate`),
  connect: (id) => api.post(`/accounts/${id}/connect`),
  telegram: (id, cfg) => api.post(`/accounts/${id}/telegram`, cfg),
};

export const grid = {
  portfolio: () => api.get("/portfolio"),
  preview: (req) => api.post("/grid/preview", req),
  deploy: (req) => api.post("/grid/deploy", req),
  sessions: () => api.get("/grid/sessions"),
  orders: (sid) => api.get(`/grid/sessions/${sid}/orders`),
  stop: (sid) => api.post(`/grid/sessions/${sid}/stop`),
  cancel: (sid) => api.post(`/grid/sessions/${sid}/cancel`),
  stopAll: () => api.post("/grid/stop-all"),
  logs: () => api.get("/logs"),
};
