// API base: same-origin /api by default (Vite proxies it in dev; on
// Render set VITE_API_URL at build time to the API service URL).
const BASE = import.meta.env.VITE_API_URL || "";

async function get(path) {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

export const api = {
  stats: () => get("/api/stats"),
  sessions: () => get("/api/sessions"),
  sessionEvents: (id) => get(`/api/sessions/${encodeURIComponent(id)}/events`),
  memories: () => get("/api/memories"),
  sources: () => get("/api/sources"),
  search: (q) => get(`/api/search?q=${encodeURIComponent(q)}&k=8`),
  dream: async () => {
    const resp = await fetch(`${BASE}/api/dream`, { method: "POST" });
    return resp.json();
  },
};
