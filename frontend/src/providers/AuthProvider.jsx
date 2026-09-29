"use client";

import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { registerTokenSetter, updateToken } from "@/lib/tokenBus";
import { refreshSession, apiFetch } from "@/lib/apiFetch";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // access_token — ТОЛЬКО в памяти, никакого localStorage
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !token && pathname !== "/login") {
      router.push("/login");
    }
  }, [loading, token, pathname, router]);

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
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
  }, []);

  const isLoginPage = pathname === "/login";
  const ready = !loading && (token || isLoginPage);

  // FE-02: RoleGuard — работник видит заглушку с мобильным приложением
  if (!loading && token && !isLoginPage && user?.role === "worker") {
    return (
      <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#0b0f19", color: "#f8fafc", padding: "24px" }}>
        <div style={{ maxWidth: "480px", width: "100%", background: "#111827", borderRadius: "16px", padding: "32px", textAlign: "center", border: "1px solid #1f2937", boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.5)" }}>
          <div style={{ width: "48px", height: "48px", borderRadius: "50%", background: "rgba(245, 158, 11, 0.1)", color: "#f59e0b", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px", fontSize: "24px" }}>
            👷
          </div>
          <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "12px" }}>Интерфейс диспетчера</h2>
          <p style={{ color: "#9ca3af", fontSize: "14px", lineHeight: "1.6", marginBottom: "24px" }}>
            Интерфейс диспетчера предназначен для операторов и администраторов. Для работы выездного сотрудника используйте мобильное приложение.
          </p>
          <button
            onClick={logout}
            style={{ width: "100%", padding: "12px", background: "#f59e0b", color: "#000", fontWeight: "600", borderRadius: "10px", border: "none", cursor: "pointer", transition: "opacity 0.2s" }}
          >
            Выйти из системы
          </button>
        </div>
      </div>
    );
  }

  const role = user?.role || null;
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
