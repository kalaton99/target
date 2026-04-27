import axios from "axios";

// MVP storage trade-off: legacy /auth/* endpoints keep the JWT in
// localStorage["target_token"]. See /app/memory/THREAT_MODEL.md for the
// full reasoning. Lobby flow uses localStorage["target_user"] (different key).
const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("target_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function wsUrl(tableId, token) {
  const httpUrl = new URL(API);
  const proto = httpUrl.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${httpUrl.host}/api/ws/table/${tableId}?token=${encodeURIComponent(token)}`;
}
