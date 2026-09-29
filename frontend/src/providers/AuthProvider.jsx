// frontend/src/providers/AuthProvider.jsx
"use client";

import React, { createContext, useContext, useState, useCallback, useEffect, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { registerTokenSetter, updateToken } from "@/lib/tokenBus";
import { refreshSession, apiFetch } from "@/lib/apiFetch";

function getRoleFromToken(token) {
  if (!token || typeof token !== "string") return null;
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    const parsed = JSON.parse(jsonPayload);
    return parsed.role || null;
  } catch {
    return null;
  }
}

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // access_token — ТОЛЬКО в памяти, никакого localStorage
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const tokenRole = useMemo(() => getRoleFromToken(token), [token]);
  const role = user?.role || tokenRole || null;

  // Регистрируем setToken в шине, чтобы apiFetch мог обновить state после рефреша
  useEffect(() => {
    registerTokenSetter((newToken) => {
      setToken(newToken);
      if (!newToken) setUser(null);
    });
  }, []);

  const restoreAttempted = React.useRef(false);

  // При монтировании пробуем восстановить сессию через refresh_token из httpOnly cookie
  useEffect(() => {
    if (restoreAttempted.current) return;
    restoreAttempted.current = true;

    const restoreSession = async () => {
      try {
        const accessToken = await refreshSession();
        setToken(accessToken);
        try {
          const res = await apiFetch("/users/me");
          if (res.ok) {
            const userData = await res.json();
            setUser(userData);
          }
        } catch {
          // ignore
        }
      } catch {
        // Нет сети или нет cookie — пользователь не авторизован
      } finally {
        setLoading(false);
      }
    };

    restoreSession();
  }, []);

  // Маршрутизация по роли и защита путей
  useEffect(() => {
    if (loading) return;

    if (!token && pathname !== "/login") {
      router.push("/login");
      return;
    }

    if (token && pathname === "/login") {
      if (role === "worker") {
        router.replace("/worker");
      } else {
        router.replace("/");
      }
      return;
    }

    if (token && role) {
      if (role === "worker" && !pathname.startsWith("/worker")) {
        router.replace("/worker");
      } else if (role !== "worker" && pathname.startsWith("/worker")) {
        router.replace("/");
      }
    }
  }, [loading, token, role, pathname, router]);

  const login = useCallback(async (accessToken) => {
    updateToken(accessToken);
    setToken(accessToken);
    try {
      const res = await apiFetch("/users/me");
      if (res.ok) {
        const userData = await res.json();
        setUser(userData);
      }
    } catch (e) {
      console.error("Failed to load user profile on login", e);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/auth/logout", {
        method: "POST",
      });
    } catch {
      // Игнорируем ошибки сети при логауте
    }
    updateToken(null);
    setToken(null);
    setUser(null);
    router.push("/login");
  }, [router]);

  const isLoginPage = pathname === "/login";
  const ready = !loading && (token || isLoginPage);
  const isReadOnly = role === "foreman";

  return (
    <AuthContext.Provider value={{ token, user, role, isReadOnly, login, logout, loading }}>
      {ready ? children : null}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
