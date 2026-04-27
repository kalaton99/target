import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";

// NOTE — This file is the **legacy** (Phase 1) auth provider for the
// /auth/login + /auth/me REST endpoints. The active Phase-11 lobby flow
// lives in `pages/LobbyPage.jsx` and persists to localStorage["target_user"]
// (different key). Keeping it here for parity with /menu, /tables, /game/:id
// pages that were not migrated to the new lobby.
//
// MVP-storage decision (see /app/memory/THREAT_MODEL.md):
// We deliberately keep the JWT in localStorage. Acceptable for an MVP with no
// real-money / PII because: (a) WebSocket auth uses ?token= query, not
// cookies; (b) JWT TTL is now 12h (was 72h); (c) /auth/me is re-checked on
// mount and 401 clears storage. Revisit when Phase 8 (Web3) lands.

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("target_token") || null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!localStorage.getItem("target_token")) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
    } catch (e) {
      // /auth/me 401/network → drop the bad/expired token and reset state.
      console.warn("auth: refresh failed; clearing legacy target_token", e);
      localStorage.removeItem("target_token");
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    localStorage.setItem("target_token", data.token);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  };

  const register = async (email, username, password) => {
    const { data } = await api.post("/auth/register", { email, username, password });
    localStorage.setItem("target_token", data.token);
    setToken(data.token);
    setUser(data.user);
    return data.user;
  };

  const logout = () => {
    localStorage.removeItem("target_token");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, token, loading, login, register, logout, refresh, setUser }}>
      {children}
    </AuthCtx.Provider>
  );
}

export const useAuth = () => useContext(AuthCtx);
