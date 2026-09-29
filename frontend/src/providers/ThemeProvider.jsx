"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";

const ThemeContext = createContext({
  theme: "dark",
  actualTheme: "dark",
  setTheme: () => {},
  toggleTheme: () => {},
});

export function ThemeProvider({ children }) {
  const [theme] = useState("dark");
  const [actualTheme] = useState("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    try {
      localStorage.removeItem("beeline_theme");
    } catch {}
    document.documentElement.setAttribute("data-theme", "dark");
    queueMicrotask(() => {
      setMounted(true);
    });
  }, []);

  const setTheme = useCallback(() => {}, []);
  const toggleTheme = useCallback(() => {}, []);

  return (
    <ThemeContext.Provider value={{ theme, actualTheme, setTheme, toggleTheme, mounted }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return ctx;
}
