"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/AuthProvider";
import styles from "./login.module.css";
import HexGrid from "./HexGrid";

export default function LoginPage() {
  const [username, setUsername] = useState("demo_observer");
  const [password, setPassword] = useState("ObserverSecret123!");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const router = useRouter();
  const { login } = useAuth();

  const handleLogin = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        throw new Error("Неверный логин или пароль");
      }

      const data = await res.json();
      login(data.access_token);
      router.push("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        {/* <div className={styles.logoBlock}>
          <div className={styles.logoCircle}>
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <path
                d="M14 3C8.477 3 4 7.477 4 13C4 18.523 8.477 23 14 23C19.523 23 24 18.523 24 13C24 7.477 19.523 3 14 3Z"
                fill="#FFC800"
              />
              <path
                d="M10 13C10 10.791 11.791 9 14 9C16.209 9 18 10.791 18 13C18 15.209 16.209 17 14 17C11.791 17 10 15.209 10 13Z"
                fill="#1C1C1E"
              />
            </svg>
          </div>
          <span className={styles.logoText}>Beeline Business</span>
        </div> */}

        <div className={styles.heading}>
          {/* <h1 className={styles.title}>Добро пожаловать</h1> */}
          <h2>Войдите в панель управления</h2>
        </div>

        <form onSubmit={handleLogin} className={styles.form}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="username">
              Логин
            </label>
            <input
              id="username"
              className={styles.input}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Введите логин"
              autoComplete="username"
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor="password">
              Пароль
            </label>
            <div className={styles.inputWrapper}>
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                className={styles.input}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Введите пароль"
                autoComplete="current-password"
              />
              <button
                type="button"
                className={styles.eyeBtn}
                onClick={() => setShowPassword((v) => !v)}
                tabIndex={-1}
                aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"}
              >
                {showPassword ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                    <line x1="1" y1="1" x2="23" y2="23" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>
                    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8"/>
                  </svg>
                )}
              </button>
            </div>
          </div>

          {error && (
            <div className={styles.errorBox}>
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M8 1.5A6.5 6.5 0 1 0 8 14.5A6.5 6.5 0 0 0 8 1.5ZM8 5V8.5M8 10.5V11"
                  stroke="#FF4444"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
              {error}
            </div>
          )}

          <button
            type="submit"
            className={`${styles.submitBtn} ${loading ? styles.loading : ""}`}
            disabled={loading}
          >
            {loading ? (
              <span className={styles.spinner} />
            ) : (
              "Войти"
            )}
          </button>
        </form>

        <p className={styles.hint}>
          Нет доступа? Обратитесь к администратору системы.
        </p>
      </div>

      <HexGrid />
    </div>
  );
}
