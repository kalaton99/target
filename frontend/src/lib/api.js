import axios from "axios";

// MVP storage trade-off: legacy /auth/* endpoints keep the JWT in
// localStorage["target_token"]. See /app/memory/THREAT_MODEL.md for the
// full reasoning. Lobby flow uses localStorage["target_user"] (different key).
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
export const API = `${BACKEND_URL}/api`;

export function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith("/api")) return `${BACKEND_URL}${path}`;
  return `${API}${path.startsWith("/") ? path : `/${path}`}`;
}

export function wsApiUrl(path) {
  const wsPath = path.startsWith("/") ? path : `/${path}`;
  if (BACKEND_URL) {
    const url = new URL(BACKEND_URL);
    const [pathname, query = ""] = wsPath.split("?", 2);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    url.pathname = pathname;
    url.search = query ? `?${query}` : "";
    url.hash = "";
    return url.toString();
  }
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}${wsPath}`;
}

export function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), options);
}

export const api = axios.create({ baseURL: API });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("target_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// 2026-05 v2 — `wsUrl` for the legacy /api/ws/table/{id} endpoint was
// removed along with `backend/realtime/`. The realtime_v2 gateway is
// the only WS surface; PlayPage builds its URL inline.
