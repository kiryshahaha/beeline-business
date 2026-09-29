// frontend/src/components/DevAccountSwitcher/DevAccountSwitcher.jsx
"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/providers/AuthProvider";
import { API_BASE } from "@/lib/apiFetch";
import styles from "./DevAccountSwitcher.module.css";

const DEMO_ACCOUNTS = [
  {
    id: "demo_worker_1",
    username: "demo_worker_1",
    password: "WorkerSecret123!",
    role: "worker",
    roleLabel: "Полевой инженер",
    badgeLabel: "Инженер (День)",
    name: "Дмитрий Кузнецов",
    shift: "08:00 – 17:00",
    skills: "ВОЛС, Подключение",
    targetRoute: "/worker",
    color: "#ffc800",
    bgTint: "rgba(255, 200, 0, 0.12)",
    accentColor: "#e6b400",
  },
  {
    id: "demo_worker_2",
    username: "demo_worker_2",
    password: "WorkerSecret123!",
    role: "worker",
    roleLabel: "Полевой инженер (Ночь)",
    badgeLabel: "Инженер (Ночь)",
    name: "Михаил Новиков",
    shift: "22:00 – 06:00",
    skills: "АВР, ВОЛС",
    targetRoute: "/worker",
    color: "#38bdf8",
    bgTint: "rgba(56, 189, 248, 0.12)",
    accentColor: "#0284c7",
  },
  {
    id: "demo_observer",
    username: "demo_observer",
    password: "ObserverSecret123!",
    role: "observer",
    roleLabel: "Диспетчер",
    badgeLabel: "Диспетчер / Observer",
    name: "Алексей Смирнов",
    shift: "Полный доступ",
    skills: "Карта заявок, Расчет маршрутов, Назначение",
    targetRoute: "/",
    color: "#a855f7",
    bgTint: "rgba(168, 85, 247, 0.12)",
    accentColor: "#9333ea",
  },
  {
    id: "demo_foreman",
    username: "demo_foreman",
    password: "ForemanSecret123!",
    role: "foreman",
    roleLabel: "Бригадир",
    badgeLabel: "Бригадир",
    name: "Иван Петров",
    shift: "Участок «Север»",
    skills: "Управление бригадами, Контроль заявок",
    targetRoute: "/",
    color: "#10b981",
    bgTint: "rgba(16, 185, 129, 0.12)",
    accentColor: "#059669",
  },
  {
    id: "demo_foreman_free",
    username: "demo_foreman_free",
    password: "ForemanSecret123!",
    role: "foreman",
    roleLabel: "Бригадир (Свободный)",
    badgeLabel: "Бригадир (Free)",
    name: "Иван Свободный",
    shift: "Резерв",
    skills: "Управление бригадами",
    targetRoute: "/",
    color: "#6ee7b7",
    bgTint: "rgba(110, 231, 183, 0.12)",
    accentColor: "#10b981",
  },
];

export default function DevAccountSwitcher() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, role, token, login, logout } = useAuth();

  const [isOpen, setIsOpen] = useState(false);
  const [switchingUser, setSwitchingUser] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [position, setPosition] = useState(null);
  const [isDragging, setIsDragging] = useState(false);

  const containerRef = useRef(null);
  const popoverRef = useRef(null);
  const dragStartRef = useRef({ x: 0, y: 0 });
  const startPosRef = useRef({ x: 0, y: 0 });
  const hasMovedRef = useRef(false);

  // Load saved position from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem("dev_switcher_pos");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (typeof parsed.x === "number" && typeof parsed.y === "number") {
          const clampedX = Math.max(8, Math.min(window.innerWidth - 60, parsed.x));
          const clampedY = Math.max(8, Math.min(window.innerHeight - 50, parsed.y));
          setPosition({ x: clampedX, y: clampedY });
        }
      }
    } catch {
      // ignore
    }
  }, []);

  // Update position bounds on resize
  useEffect(() => {
    const handleResize = () => {
      setPosition((prev) => {
        if (!prev) return null;
        return {
          x: Math.max(8, Math.min(window.innerWidth - 60, prev.x)),
          y: Math.max(8, Math.min(window.innerHeight - 50, prev.y)),
        };
      });
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Close on Escape or click outside
  useEffect(() => {
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    }
    function handleKeyDown(event) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  // Pointer drag events
  const handlePointerDown = (e) => {
    if (e.button !== 0) return;
    if (popoverRef.current && popoverRef.current.contains(e.target)) return;

    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    dragStartRef.current = { x: e.clientX, y: e.clientY };
    startPosRef.current = { x: rect.left, y: rect.top };
    hasMovedRef.current = false;
    setIsDragging(true);

    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // ignore
    }
  };

  const handlePointerMove = (e) => {
    if (!isDragging) return;

    const dx = e.clientX - dragStartRef.current.x;
    const dy = e.clientY - dragStartRef.current.y;

    if (!hasMovedRef.current && Math.hypot(dx, dy) > 4) {
      hasMovedRef.current = true;
    }

    if (hasMovedRef.current) {
      const newX = Math.max(8, Math.min(window.innerWidth - 60, startPosRef.current.x + dx));
      const newY = Math.max(8, Math.min(window.innerHeight - 50, startPosRef.current.y + dy));
      setPosition({ x: newX, y: newY });
    }
  };

  const handlePointerUp = (e) => {
    if (!isDragging) return;

    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
    setIsDragging(false);

    if (hasMovedRef.current) {
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      const finalX = Math.max(8, Math.min(window.innerWidth - 60, startPosRef.current.x + dx));
      const finalY = Math.max(8, Math.min(window.innerHeight - 50, startPosRef.current.y + dy));
      localStorage.setItem("dev_switcher_pos", JSON.stringify({ x: finalX, y: finalY }));
    } else {
      setIsOpen((prev) => !prev);
    }
  };

  const handlePointerCancel = (e) => {
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // ignore
    }
    setIsDragging(false);
  };

  const handleSwitchAccount = async (account) => {
    if (switchingUser) return;
    setSwitchingUser(account.username);
    setErrorMsg(null);

    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          username: account.username,
          password: account.password,
        }),
      });

      if (!res.ok) {
        let errDetail = `HTTP ${res.status}`;
        try {
          const errData = await res.json();
          if (errData?.detail) errDetail = errData.detail;
        } catch {
          // ignore
        }
        throw new Error(`Ошибка входа (${errDetail})`);
      }

      const data = await res.json();

      // Reset query cache to purge old user data
      queryClient.clear();

      // Save token in memory and fetch user profile
      await login(data.access_token);

      // Route to destination
      router.push(account.targetRoute);
      setIsOpen(false);
    } catch (err) {
      console.error("Dev switcher login error:", err);
      setErrorMsg(err.message || "Не удалось переключить аккаунт");
    } finally {
      setSwitchingUser(null);
    }
  };

  const handleLogout = async () => {
    try {
      queryClient.clear();
      await logout();
      router.push("/login");
      setIsOpen(false);
    } catch (err) {
      console.error("Logout error:", err);
    }
  };

  const currentAccount = DEMO_ACCOUNTS.find(
    (acc) => acc.username === user?.username
  );

  const isNearBottom = position ? position.y > (typeof window !== "undefined" ? window.innerHeight * 0.5 : 400) : false;
  const isNearRight = position ? position.x > (typeof window !== "undefined" ? window.innerWidth * 0.5 : 400) : true;

  return (
    <aside
      aria-label="Переключатель тестовых аккаунтов (Dev Tools)"
      className={`${styles.devContainer} ${isOpen ? styles.devContainerOpen : ""} ${isDragging ? styles.devContainerDragging : ""}`}
      ref={containerRef}
      style={
        position
          ? {
              left: `${position.x}px`,
              top: `${position.y}px`,
              right: "auto",
              bottom: "auto",
            }
          : undefined
      }
    >
      {/* Floating Trigger Button */}
      <button
        type="button"
        className={`${styles.floatBtn} ${isOpen ? styles.floatBtnActive : ""} ${isDragging ? styles.floatBtnDragging : ""}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerCancel}
        title="Тестовый переключатель аккаунтов (потяните, чтобы переместить)"
      >
        <div className={styles.dragGrip} title="Потяните для перемещения">
          <svg width="6" height="12" viewBox="0 0 6 12" fill="currentColor">
            <circle cx="1.5" cy="2" r="1.1" />
            <circle cx="4.5" cy="2" r="1.1" />
            <circle cx="1.5" cy="6" r="1.1" />
            <circle cx="4.5" cy="6" r="1.1" />
            <circle cx="1.5" cy="10" r="1.1" />
            <circle cx="4.5" cy="10" r="1.1" />
          </svg>
        </div>

        <div className={styles.btnIconArea}>
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
            <circle cx="9" cy="7" r="4" />
            <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
          </svg>
        </div>

        <div className={styles.btnContent}>
          <span className={styles.devTag}>TEST</span>
          <span className={styles.roleLabel}>
            {user?.username ? user.username : role || "Гость"}
          </span>
        </div>

        <svg
          className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ""}`}
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {/* Popover Panel */}
      {isOpen && (
        <div
          ref={popoverRef}
          className={`${styles.popover} ${isNearBottom ? styles.popoverUp : styles.popoverDown} ${isNearRight ? styles.popoverRight : styles.popoverLeft}`}
        >
          {/* Header */}
          <div className={styles.popoverHeader}>
            <div className={styles.headerLeft}>
              <div className={styles.headerTitleRow}>
                <span className={styles.devBadge}>DEV TOOLS</span>
                <span className={styles.popoverTitle}>Смена роли / аккаунта</span>
              </div>
              <p className={styles.headerSubtitle}>
                Быстрый вход в 1 клик для проверки прав и интерфейсов
              </p>
            </div>
            <button
              type="button"
              className={styles.closeBtn}
              onClick={() => setIsOpen(false)}
              title="Закрыть"
            >
              ×
            </button>
          </div>

          {/* Current Active User Banner */}
          <div className={styles.currentBanner}>
            <div className={styles.currentIndicator} />
            <div className={styles.currentInfo}>
              <span className={styles.currentSmallLabel}>ТЕКУЩАЯ СЕССИЯ</span>
              <div className={styles.currentNameRow}>
                <span className={styles.currentName}>
                  {user
                    ? `${user.surname || ""} ${user.name || ""} ${user.lastname || ""}`.trim() || user.username
                    : token
                    ? "Авторизован"
                    : "Не авторизован (Гость)"}
                </span>
                {user?.username && (
                  <code className={styles.currentUsername}>@{user.username}</code>
                )}
                {role && <span className={styles.currentRoleBadge}>{role}</span>}
              </div>
            </div>
          </div>

          {errorMsg && (
            <div className={styles.errorBox}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{errorMsg}</span>
            </div>
          )}

          {/* Accounts List */}
          <div className={styles.accountsList}>
            {DEMO_ACCOUNTS.map((acc) => {
              const isActive = user?.username === acc.username;
              const isBusy = switchingUser === acc.username;

              return (
                <div
                  key={acc.id}
                  className={`${styles.accountCard} ${isActive ? styles.accountCardActive : ""}`}
                >
                  <div className={styles.cardHeaderRow}>
                    <div className={styles.cardRoleBlock}>
                      <span
                        className={styles.badgePill}
                        style={{
                          background: acc.bgTint,
                          color: acc.color,
                          borderColor: `${acc.color}40`,
                        }}
                      >
                        {acc.badgeLabel}
                      </span>
                      <span className={styles.accountName}>{acc.name}</span>
                    </div>

                    {isActive && (
                      <span className={styles.activeCheck}>
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                        Текущий
                      </span>
                    )}
                  </div>

                  <div className={styles.cardMetaRow}>
                    <code className={styles.usernameCode}>@{acc.username}</code>
                    <span className={styles.metaDivider}>•</span>
                    <span className={styles.metaShift}>{acc.shift}</span>
                  </div>

                  <div className={styles.cardSkillsRow}>
                    <span className={styles.skillsText}>{acc.skills}</span>
                  </div>

                  <button
                    type="button"
                    className={`${styles.switchBtn} ${isActive ? styles.switchBtnCurrent : ""}`}
                    disabled={isActive || !!switchingUser}
                    onClick={() => handleSwitchAccount(acc)}
                  >
                    {isBusy ? (
                      <span className={styles.spinner} />
                    ) : isActive ? (
                      "Активен сейчас"
                    ) : (
                      `Войти как ${acc.username}`
                    )}
                  </button>
                </div>
              );
            })}
          </div>

          {/* Footer Actions */}
          <div className={styles.popoverFooter}>
            <button
              type="button"
              className={styles.logoutBtn}
              onClick={handleLogout}
              disabled={!token}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
              <span>Выйти из аккаунта</span>
            </button>

            <span className={styles.devDisclaimer}>
              Только для стенда / локального тестирования
            </span>
          </div>
        </div>
      )}
    </aside>
  );
}
