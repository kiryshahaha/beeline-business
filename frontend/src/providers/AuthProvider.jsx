"use client";

import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { registerTokenSetter } from "@/lib/tokenBus";
import { refreshSession } from "@/lib/apiFetch";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // access_token — ТОЛЬКО в памяти, никакого localStorage
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  // Регистрируем setToken в шине, чтобы apiFetch мог обновить state после рефреша
  useEffect(() => {
    registerTokenSetter(setToken);
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
      } catch {
        // Нет сети или нет cookie — пользователь не авторизован
      } finally {
        setLoading(false);
      }
    };

    restoreSession();
  }, []);

  const login = useCallback((accessToken) => {
    // refresh_token сервер поставил в httpOnly cookie — нам не нужно его трогать
    setToken(accessToken);
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Игнорируем ошибки сети при логауте
    }
    setToken(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
