import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, clearToken, getToken, setToken } from "../api";
import type { Me } from "../types";
import { useSessionTimeout } from "./useSessionTimeout";

type AuthValue = {
  me: Me | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  has: (permission: string) => boolean;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/auth/me"));
    } catch {
      clearToken();
      setMe(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const expired = () => setMe(null);
    window.addEventListener("eaststone-auth-expired", expired);
    return () => window.removeEventListener("eaststone-auth-expired", expired);
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const result = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    setToken(result.access_token);
    sessionStorage.setItem("eaststone_training_matrix_last_activity", String(Date.now()));
    sessionStorage.removeItem("eaststone_training_matrix_session_end_reason");
    setMe(await api<Me>("/auth/me"));
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      clearToken();
      sessionStorage.removeItem("eaststone_training_matrix_last_activity");
      setMe(null);
    }
  }, []);

  useSessionTimeout(me, logout);

  const value = useMemo<AuthValue>(
    () => ({ me, loading, login, logout, refresh, has: (permission) => Boolean(me?.permissions.includes(permission)) }),
    [me, loading, login, logout, refresh],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
