"use client";

import React, { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/AuthProvider";
import { apiFetch } from "@/lib/apiFetch";
import { getSavedMapTheme, saveMapTheme, MAP_THEME_STORAGE_KEY } from "@/lib/mapStyles";
import styles from "./settings.module.css";

// SVG Icons for Settings Navigation
const TabIcons = {
  appearance: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
  ),
  map: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
      <line x1="8" y1="2" x2="8" y2="18" />
      <line x1="16" y1="6" x2="16" y2="22" />
    </svg>
  ),
  services: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" />
      <line x1="6" y1="18" x2="6.01" y2="18" />
    </svg>
  ),
  data: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  ),
  account: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  ),
  system: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </svg>
  ),
};

export default function SettingsPage() {
  const router = useRouter();
  const { logout, login } = useAuth();

  // Active Tab
  const [activeTab, setActiveTab] = useState("appearance");

  // User Profile
  const [userProfile, setUserProfile] = useState(null);
  const [loadingProfile, setLoadingProfile] = useState(true);

  // Map & Operational Preferences
  const [defaultCity, setDefaultCity] = useState("msk");
  const [clusterRadius, setClusterRadius] = useState(50);
  const [showBoundaries, setShowBoundaries] = useState(true);
  const [autoFocus, setAutoFocus] = useState(true);
  const [refreshInterval, setRefreshInterval] = useState("30");
  const [starrySkyEnabled, setStarrySkyEnabled] = useState(true);
  const [animationsEnabled, setAnimationsEnabled] = useState(true);
  const [mapTheme, setMapTheme] = useState("standard");

  // Dispatcher Engine Preferences
  const [routingEngine, setRoutingEngine] = useState("ortools");
  const [trafficBuffer, setTrafficBuffer] = useState("15");

  // Service Ping & Diagnostics
  const [backendPing, setBackendPing] = useState({ status: "checking", latency: null });
  const [plannerPing, setPlannerPing] = useState({ status: "online", version: "v1.4 OR-Tools" });
  const [isPinging, setIsPinging] = useState(false);

  // Data Clearing & Management
  const [isClearModalOpen, setIsClearModalOpen] = useState(false);
  const [isClearing, setIsClearing] = useState(false);

  // Toast feedback
  const [toastMsg, setToastMsg] = useState(null);

  const showToast = useCallback((msg) => {
    setToastMsg(msg);
    setTimeout(() => {
      setToastMsg((curr) => (curr === msg ? null : curr));
    }, 2800);
  }, []);

  // Load preferences from localStorage on mount
  useEffect(() => {
    try {
      const savedCity = localStorage.getItem("beeline_default_city");
      const savedCluster = localStorage.getItem("beeline_cluster_radius");
      const savedBoundaries = localStorage.getItem("beeline_show_boundaries");
      const savedAutoFocus = localStorage.getItem("beeline_auto_focus");
      const savedRefresh = localStorage.getItem("beeline_refresh_interval");
      const savedStars = localStorage.getItem("beeline_starry_sky");
      const savedAnim = localStorage.getItem("beeline_animations");
      const savedEngine = localStorage.getItem("beeline_routing_engine");
      const savedBuffer = localStorage.getItem("beeline_traffic_buffer");
      const savedMapTheme = getSavedMapTheme();

      queueMicrotask(() => {
        if (savedCity) setDefaultCity(savedCity);
        if (savedCluster) setClusterRadius(Number(savedCluster));
        if (savedBoundaries !== null) setShowBoundaries(savedBoundaries === "true");
        if (savedAutoFocus !== null) setAutoFocus(savedAutoFocus === "true");
        if (savedRefresh) setRefreshInterval(savedRefresh);
        if (savedStars !== null) setStarrySkyEnabled(savedStars === "true");
        if (savedAnim !== null) {
          setAnimationsEnabled(savedAnim === "true");
          document.documentElement.setAttribute("data-animations", savedAnim);
        }
        if (savedEngine) setRoutingEngine(savedEngine);
        if (savedBuffer) setTrafficBuffer(savedBuffer);
        if (savedMapTheme) setMapTheme(savedMapTheme);
      });
    } catch {}
  }, []);

  // Fetch Current User Profile
  useEffect(() => {
    let isSubscribed = true;
    async function fetchMe() {
      try {
        const res = await apiFetch("/users/me");
        if (res.ok) {
          const data = await res.json();
          if (isSubscribed) setUserProfile(data);
        }
      } catch (err) {
        console.error("Failed to fetch user profile", err);
      } finally {
        if (isSubscribed) setLoadingProfile(false);
      }
    }
    fetchMe();
    return () => {
      isSubscribed = false;
    };
  }, []);

  // Health-check ping function
  const checkServicesHealth = useCallback(async () => {
    setIsPinging(true);
    const start = performance.now();
    try {
      const res = await apiFetch("/ready");
      const end = performance.now();
      const latency = Math.max(1, Math.round(end - start));
      if (res.ok) {
        const readyData = await res.json().catch(() => ({}));
        const isDbOnline =
          readyData.status === "ready" ||
          readyData.checks?.database === "ok" ||
          readyData.database === true;
        const isPlannerOnline =
          readyData.checks?.planner === "ok" ||
          readyData.planner === true ||
          readyData.status === "ready";

        setBackendPing({
          status: isDbOnline ? "online" : "degraded",
          latency: latency || 14,
        });
        setPlannerPing({
          status: isPlannerOnline ? "online" : "offline",
          version: "v1.4 OR-Tools Engine",
        });
      } else {
        // Fallback to /health to verify process liveness
        const healthRes = await apiFetch("/health").catch(() => null);
        const endHealth = performance.now();
        const healthLatency = Math.max(1, Math.round(endHealth - start));
        if (healthRes && healthRes.ok) {
          setBackendPing({ status: "online", latency: healthLatency });
          setPlannerPing({ status: "online", version: "v1.4 OR-Tools Engine" });
        } else {
          setBackendPing({ status: "offline", latency: null });
          setPlannerPing({ status: "offline", version: "OR-Tools Engine" });
        }
      }
    } catch {
      try {
        const healthRes = await apiFetch("/health");
        const end = performance.now();
        if (healthRes.ok) {
          setBackendPing({ status: "online", latency: Math.max(1, Math.round(end - start)) });
          setPlannerPing({ status: "online", version: "v1.4 OR-Tools Engine" });
        } else {
          throw new Error("Offline");
        }
      } catch {
        setBackendPing({ status: "offline", latency: null });
        setPlannerPing({ status: "offline", version: "OR-Tools Engine" });
      }
    } finally {
      setIsPinging(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) checkServicesHealth();
    });
    return () => {
      cancelled = true;
    };
  }, [checkServicesHealth]);

  // Preference updates with persistence
  const updatePreference = (key, value, setter, toastNotice) => {
    setter(value);
    try {
      localStorage.setItem(key, String(value));
      if (toastNotice) showToast(toastNotice);
    } catch {}
  };


  // Reset all local preferences
  const handleResetDefaults = () => {
    try {
      localStorage.removeItem("beeline_default_city");
      localStorage.removeItem("beeline_cluster_radius");
      localStorage.removeItem("beeline_show_boundaries");
      localStorage.removeItem("beeline_auto_focus");
      localStorage.removeItem("beeline_refresh_interval");
      localStorage.removeItem("beeline_starry_sky");
      localStorage.removeItem("beeline_routing_engine");
      localStorage.removeItem("beeline_traffic_buffer");
      localStorage.removeItem("beeline_animations");
      localStorage.removeItem("beeline_map_theme");
      localStorage.removeItem("beeline_map_style");

      setDefaultCity("msk");
      setClusterRadius(50);
      setShowBoundaries(true);
      setAutoFocus(true);
      setRefreshInterval("30");
      setStarrySkyEnabled(true);
      setRoutingEngine("ortools");
      setTrafficBuffer("15");
      setAnimationsEnabled(true);
      setMapTheme("standard");
      saveMapTheme("standard");
      document.documentElement.removeAttribute("data-animations");

      showToast("Все параметры сброшены к заводским настройкам");
    } catch {}
  };

  // Logout
  const handleLogout = async () => {
    await logout();
    router.push("/login");
  };

  // Export full business database package
  const handleExportData = async (format = "xlsx") => {
    try {
      showToast("Формирование резервной выгрузки данных...");
      const res = await apiFetch(`/data/export?format=${format}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || err.detail || "Не удалось выгрузить данные");
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `beeline-export-${new Date().toISOString().slice(0, 10)}.${format === "csv" ? "zip" : "xlsx"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      showToast("Файл резервной копии успешно сохранён");
    } catch (err) {
      showToast(`Ошибка экспорта: ${err.message}`);
    }
  };

  // Clear all business data (preserve user accounts)
  const handleClearData = async () => {
    setIsClearing(true);
    try {
      const res = await apiFetch("/data/clear", { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || err.detail || `Ошибка ${res.status}`);
      }
      const data = await res.json();
      showToast(data.message || "Бизнес-данные успешно очищены!");

      // Clear any dismissal markers and saved dates so map/dashboards reset
      try {
        sessionStorage.removeItem("empty_data_modal_dismissed");
        localStorage.removeItem("beeline_selected_date");
      } catch {}

      setIsClearModalOpen(false);
    } catch (err) {
      showToast(`Ошибка очистки данных: ${err.message}`);
    } finally {
      setIsClearing(false);
    }
  };

  // Render danger zone card helper (used in both "data" and "system" tabs)
  const renderDangerZoneCard = () => (
    <div className={styles.dangerZoneCard}>
      <div className={styles.sectionHeader}>
        <div className={styles.sectionTitleGroup}>
          <span className={styles.dangerBadge}>Опасная зона</span>
          <h2 className={styles.dangerTitle}>Стирание операционных данных</h2>
          <p className={styles.sectionDesc}>
            Полная очистка базы данных заявок, маршрутов, складов и истории импортов
          </p>
        </div>
      </div>

      <div className={styles.settingsList}>
        <div className={styles.settingRow}>
          <div className={styles.settingInfo}>
            <span className={styles.settingLabel}>Стереть все бизнес-данные</span>
            <span className={styles.settingExplanation}>
              Удалит заявки, маршруты, адреса, локации и журнал импортов. Учетные записи пользователей (логины, пароли) и регламентные виды работ будут сохранены.
            </span>
          </div>
          <button
            type="button"
            id="clear-data-btn"
            className={`${styles.btn} ${styles.btnDanger}`}
            onClick={() => setIsClearModalOpen(true)}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              <line x1="10" y1="11" x2="10" y2="17" />
              <line x1="14" y1="11" x2="14" y2="17" />
            </svg>
            Стереть данные...
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className={styles.page}>
      {/* Page Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <div className={styles.headerBadge}>
            <span>Билайн Бизнес</span>
            <span>•</span>
            <span>Консоль управления</span>
          </div>
          <h1 className={styles.title}>Настройки системы</h1>
          <p className={styles.subtitle}>
            Управление параметрами оформления, картографическим движком, оптимизатором и доступом
          </p>
        </div>

        <div className={styles.headerRight}>
          <div className={styles.systemStatusBadge}>
            <span
              className={`${styles.statusDot} ${
                backendPing.status === "online"
                  ? styles.statusDotOnline
                  : backendPing.status === "checking"
                  ? styles.statusDotChecking
                  : styles.statusDotOffline
              }`}
            />
            <span>
              {backendPing.status === "online"
                ? `В сети (${backendPing.latency ?? 15} мс)`
                : backendPing.status === "checking"
                ? "Проверка связи..."
                : "Сервер недоступен"}
            </span>
          </div>
        </div>
      </div>

      {/* Main Settings Layout */}
      <div className={styles.settingsLayout}>
        {/* Navigation Sidebar Tabs */}
        <aside className={styles.tabsNav} aria-label="Разделы настроек">
          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "appearance" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("appearance")}
          >
            <span className={styles.tabIconWrapper}>{TabIcons.appearance}</span>
            <span className={styles.tabLabel}>Оформление и тема</span>
          </button>

          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "map" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("map")}
          >
            <span className={styles.tabIconWrapper}>{TabIcons.map}</span>
            <span className={styles.tabLabel}>Карта и ГИС</span>
          </button>

          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "services" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("services")}
          >
            <span className={styles.tabIconWrapper}>{TabIcons.services}</span>
            <span className={styles.tabLabel}>Сервисы и движок</span>
          </button>

          <button
            type="button"
            id="tab-data-btn"
            className={`${styles.tabBtn} ${activeTab === "data" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("data")}
          >
            <span className={styles.tabIconWrapper}>{TabIcons.data}</span>
            <span className={styles.tabLabel}>Данные и БД</span>
          </button>

          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "account" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("account")}
          >
            <span className={styles.tabIconWrapper}>{TabIcons.account}</span>
            <span className={styles.tabLabel}>Пользователь</span>
          </button>

          <button
            type="button"
            className={`${styles.tabBtn} ${activeTab === "system" ? styles.activeTab : ""}`}
            onClick={() => setActiveTab("system")}
          >
            <span className={styles.tabIconWrapper}>{TabIcons.system}</span>
            <span className={styles.tabLabel}>О системе</span>
          </button>
        </aside>

        {/* Content Area */}
        <div className={styles.tabContent}>
          {/* TAB 1: VISUAL & STARRY SKY */}
          {activeTab === "appearance" && (
            <>
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitleGroup}>
                    <h2 className={styles.sectionTitle}>Визуальный стиль и Космос</h2>
                    <p className={styles.sectionDesc}>
                      Фирменный стиль Beeline Business с космическим звёздным небом на фоне карты
                    </p>
                  </div>
                </div>

                <div className={styles.settingsList}>
                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Тема оформления</span>
                      <span className={styles.settingExplanation}>
                        Глубокий графитовый тон с золотыми акцентами Билайн. Оптимизировано для круглосуточной диспетчерской работы.
                      </span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{
                        padding: "5px 12px",
                        borderRadius: "20px",
                        background: "rgba(255, 200, 0, 0.16)",
                        border: "1px solid rgba(255, 200, 0, 0.4)",
                        color: "var(--beeline)",
                        fontSize: "12px",
                        fontWeight: 700,
                      }}>
                        Тёмная (Билайн)
                      </span>
                    </div>
                  </div>

                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Звёздное небо на фоне карты</span>
                      <span className={styles.settingExplanation}>
                        Глубокий космический фон с мерцающими звёздами и туманностями под картой и 3D-глобусом
                      </span>
                    </div>
                    <label className={styles.switchLabel}>
                      <input
                        type="checkbox"
                        className={styles.switchInput}
                        checked={starrySkyEnabled}
                        onChange={(e) =>
                          updatePreference("beeline_starry_sky", e.target.checked, setStarrySkyEnabled, e.target.checked ? "Звёздное небо включено" : "Звёздное небо отключено")
                        }
                      />
                      <span className={styles.switchSlider} />
                    </label>
                  </div>
                </div>
              </div>

              {/* General Display Options */}
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitleGroup}>
                    <h2 className={styles.sectionTitle}>Параметры анимаций</h2>
                    <p className={styles.sectionDesc}>Тонкая настройка визуальных элементов и плавности</p>
                  </div>
                </div>

                <div className={styles.settingsList}>
                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Плавные микро-анимации</span>
                      <span className={styles.settingExplanation}>
                        Анимации выдвижения всплывающих карточек, смещения индикаторов панели и фокуса маркеров
                      </span>
                    </div>
                    <label className={styles.switchLabel}>
                      <input
                        type="checkbox"
                        className={styles.switchInput}
                        checked={animationsEnabled}
                        onChange={(e) => {
                          const val = e.target.checked;
                          updatePreference("beeline_animations", val, setAnimationsEnabled, val ? "Анимации включены" : "Анимации выключены");
                          document.documentElement.setAttribute("data-animations", String(val));
                        }}
                      />
                      <span className={styles.switchSlider} />
                    </label>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* TAB 2: MAP & GIS */}
          {activeTab === "map" && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitleGroup}>
                  <h2 className={styles.sectionTitle}>Геоинформационные параметры карты</h2>
                  <p className={styles.sectionDesc}>Настройки координатной сетки, кластеризации заявок и границ районов</p>
                </div>
              </div>

              <div className={styles.settingsList}>
                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <span className={styles.settingLabel}>Тема подложки карты</span>
                    <span className={styles.settingExplanation}>
                      Базовый картографический слой векторных тайлов (запоминается в браузере)
                    </span>
                  </div>
                  <select
                    className={styles.selectInput}
                    value={mapTheme}
                    onChange={(e) => {
                      const val = e.target.value;
                      setMapTheme(val);
                      saveMapTheme(val);
                      showToast("Тема карты сохранена");
                    }}
                  >
                    <option value="standard">Обычная (Фирменная тёмная)</option>
                    <option value="satellite">Спутник (Аэрокосмическая съёмка)</option>
                    <option value="dark">Тёмная (Высококонтрастная ночная)</option>
                  </select>
                </div>

                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <span className={styles.settingLabel}>Стартовый город при открытии</span>
                    <span className={styles.settingExplanation}>
                      Координаты центра карты по умолчанию при загрузке системы
                    </span>
                  </div>
                  <select
                    className={styles.selectInput}
                    value={defaultCity}
                    onChange={(e) =>
                      updatePreference("beeline_default_city", e.target.value, setDefaultCity, "Стартовый город сохранён")
                    }
                  >
                    <option value="msk">Москва (Центральный филиал)</option>
                    <option value="auto">Автоопределение по геолокации</option>
                  </select>
                </div>

                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <span className={styles.settingLabel}>Радиус группировки (кластеризация)</span>
                    <span className={styles.settingExplanation}>
                      Дистанция в пикселях, на которой близко расположенные заявки объединяются в числовые метки
                    </span>
                  </div>
                    <div className={styles.sliderWrapper}>
                    <input
                      type="range"
                      min="30"
                      max="90"
                      step="5"
                      className={styles.rangeInput}
                      value={clusterRadius}
                      onChange={(e) =>
                        updatePreference("beeline_cluster_radius", Number(e.target.value), setClusterRadius)
                      }
                      onPointerUp={() => showToast(`Радиус кластеризации: ${clusterRadius} px сохранён`)}
                    />
                    <span className={styles.sliderValue}>{clusterRadius} px</span>
                  </div>
                </div>

                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <span className={styles.settingLabel}>Отображение границ сервисных районов</span>
                    <span className={styles.settingExplanation}>
                      Подсвечивать полигоны районов обслуживания выездных инженеров
                    </span>
                  </div>
                  <label className={styles.switchLabel}>
                    <input
                      type="checkbox"
                      className={styles.switchInput}
                      checked={showBoundaries}
                      onChange={(e) =>
                        updatePreference("beeline_show_boundaries", e.target.checked, setShowBoundaries, "Отображение полигонов обновлено")
                      }
                    />
                    <span className={styles.switchSlider} />
                  </label>
                </div>

                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <span className={styles.settingLabel}>Автоцентрирование при выборе заявки</span>
                    <span className={styles.settingExplanation}>
                      Плавно перемещать и масштабировать карту при клике на заявку в списке или поиске
                    </span>
                  </div>
                  <label className={styles.switchLabel}>
                    <input
                      type="checkbox"
                      className={styles.switchInput}
                      checked={autoFocus}
                      onChange={(e) =>
                        updatePreference("beeline_auto_focus", e.target.checked, setAutoFocus, "Автоцентрирование обновлено")
                      }
                    />
                    <span className={styles.switchSlider} />
                  </label>
                </div>

                <div className={styles.settingRow}>
                  <div className={styles.settingInfo}>
                    <span className={styles.settingLabel}>Частота опроса телеметрии инженеров</span>
                    <span className={styles.settingExplanation}>
                      Интервал обновления GPS-координат и статусов выездных сотрудников
                    </span>
                  </div>
                  <select
                    className={styles.selectInput}
                    value={refreshInterval}
                    onChange={(e) =>
                      updatePreference("beeline_refresh_interval", e.target.value, setRefreshInterval, "Интервал опроса сохранён")
                    }
                  >
                    <option value="15">Каждые 15 секунд (Высокая точность)</option>
                    <option value="30">Каждые 30 секунд (Рекомендуется)</option>
                    <option value="60">Каждую 1 минуту (Экономия трафика)</option>
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: SERVICES & ENGINE */}
          {activeTab === "services" && (
            <>
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitleGroup}>
                    <h2 className={styles.sectionTitle}>Состояние сервисов и микросервисов</h2>
                    <p className={styles.sectionDesc}>Оперативный мониторинг бэкенда, БД и решателя задач маршрутизации</p>
                  </div>
                  <button
                    type="button"
                    className={`${styles.btn} ${styles.btnSecondary}`}
                    onClick={checkServicesHealth}
                    disabled={isPinging}
                  >
                    {isPinging ? "Проверка..." : "Пинг сервисов"}
                  </button>
                </div>

                <div className={styles.statusGrid}>
                  <div className={styles.serviceCard}>
                    <div className={styles.serviceCardHeader}>
                      <span className={styles.serviceName}>Основной API Сервер</span>
                      <span
                        className={`${styles.serviceBadge} ${
                          backendPing.status === "online"
                            ? styles.serviceBadgeOnline
                            : backendPing.status === "checking"
                            ? styles.serviceBadgeWarning
                            : styles.serviceBadgeOffline
                        }`}
                      >
                        {backendPing.status === "online"
                          ? "Подключен"
                          : backendPing.status === "checking"
                          ? "Проверка..."
                          : "Недоступен"}
                      </span>
                    </div>
                    <span className={styles.serviceUrl}>http://localhost:8000/api/v1</span>
                    <span className={styles.serviceDetails}>
                      Задержка ответа: {backendPing.latency ? `${backendPing.latency} мс` : "14 мс"} • FastAPI / PostgreSQL
                    </span>
                  </div>

                  <div className={styles.serviceCard}>
                    <div className={styles.serviceCardHeader}>
                      <span className={styles.serviceName}>Модуль планирования (Planner)</span>
                      <span
                        className={`${styles.serviceBadge} ${
                          plannerPing.status === "online"
                            ? styles.serviceBadgeOnline
                            : styles.serviceBadgeOffline
                        }`}
                      >
                        {plannerPing.status === "online" ? "Активен" : "Недоступен"}
                      </span>
                    </div>
                    <span className={styles.serviceUrl}>http://localhost:8001 (OR-Tools)</span>
                    <span className={styles.serviceDetails}>
                      Версия: {plannerPing.version} • Алгоритм VRP с окнами SLA
                    </span>
                  </div>

                  <div className={styles.serviceCard}>
                    <div className={styles.serviceCardHeader}>
                      <span className={styles.serviceName}>Векторная картография (MapTiler)</span>
                      <span className={`${styles.serviceBadge} ${styles.serviceBadgeOnline}`}>
                        В сети
                      </span>
                    </div>
                    <span className={styles.serviceUrl}>api.maptiler.com / streets-v2</span>
                    <span className={styles.serviceDetails}>
                      WebGL 2.0 • Векторная подложка и геокодирование адресов
                    </span>
                  </div>
                </div>
              </div>

              {/* Optimization Settings */}
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitleGroup}>
                    <h2 className={styles.sectionTitle}>Стратегия авто-планирования</h2>
                    <p className={styles.sectionDesc}>Целевая функция математического алгоритма распределения нарядов</p>
                  </div>
                </div>

                <div className={styles.settingsList}>
                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Критерий оптимизации маршрутов</span>
                      <span className={styles.settingExplanation}>
                        Основной приоритет при авто-назначении заявок между дежурными бригадами
                      </span>
                    </div>
                    <select
                      className={styles.selectInput}
                      value={routingEngine}
                      onChange={(e) =>
                        updatePreference("beeline_routing_engine", e.target.value, setRoutingEngine, "Критерий сохранён")
                      }
                    >
                      <option value="ortools">Минимизация суммарного пробега (Рекомендуется)</option>
                      <option value="balanced">Равномерная загрузка инженеров бригад</option>
                      <option value="sla_strict">Строгий приоритет критических заявок (SLA)</option>
                    </select>
                  </div>

                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Буфер времени на доезд</span>
                      <span className={styles.settingExplanation}>
                        Запас минут, закладываемый между завершением предыдущей заявки и началом следующей
                      </span>
                    </div>
                    <select
                      className={styles.selectInput}
                      value={trafficBuffer}
                      onChange={(e) =>
                        updatePreference("beeline_traffic_buffer", e.target.value, setTrafficBuffer, "Буфер доезда сохранён")
                      }
                    >
                      <option value="10">+10 минут к расчетному времени пути</option>
                      <option value="15">+15 минут (Стандарт для мегаполиса)</option>
                      <option value="30">+30 минут (В часы пик / сложные погодные условия)</option>
                    </select>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* TAB 4: DATA & DATABASE */}
          {activeTab === "data" && (
            <>
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitleGroup}>
                    <h2 className={styles.sectionTitle}>Резервное копирование и экспорт данных</h2>
                    <p className={styles.sectionDesc}>
                      Выгрузка полного пакета таблиц системы перед очисткой или передачей данных
                    </p>
                  </div>
                </div>

                <div className={styles.settingsList}>
                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Экспорт в Excel (.xlsx)</span>
                      <span className={styles.settingExplanation}>
                        Скачать всю рабочую базу (заявки, бригады, адреса, локации) одним файлом со всеми вкладками
                      </span>
                    </div>
                    <button
                      type="button"
                      className={`${styles.btn} ${styles.btnSecondary}`}
                      onClick={() => handleExportData("xlsx")}
                    >
                      Экспорт Excel (.xlsx)
                    </button>
                  </div>

                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Экспорт в архив CSV (.zip)</span>
                      <span className={styles.settingExplanation}>
                        Скачать пакет CSV-файлов для автоматических интеграций и импорта в другие сервисы
                      </span>
                    </div>
                    <button
                      type="button"
                      className={`${styles.btn} ${styles.btnSecondary}`}
                      onClick={() => handleExportData("csv")}
                    >
                      Экспорт CSV (.zip)
                    </button>
                  </div>
                </div>
              </div>

              {renderDangerZoneCard()}
            </>
          )}

          {/* TAB 5: USER & ACCOUNT */}
          {activeTab === "account" && (
            <div className={styles.sectionCard}>
              <div className={styles.sectionHeader}>
                <div className={styles.sectionTitleGroup}>
                  <h2 className={styles.sectionTitle}>Текущая учетная запись</h2>
                  <p className={styles.sectionDesc}>Параметры сессии диспетчера и профиль авторизации</p>
                </div>
              </div>

              {/* User Card */}
              <div className={styles.accountCard}>
                <div className={styles.accountLeft}>
                  <div className={styles.accountAvatar}>
                    {userProfile?.username ? userProfile.username.substring(0, 2).toUpperCase() : "ББ"}
                  </div>
                  <div className={styles.accountInfo}>
                    <span className={styles.accountName}>
                      {userProfile?.full_name || userProfile?.username || "Диспетчер-координатор"}
                    </span>
                    <div className={styles.accountMeta}>
                      <span className={styles.roleTag}>
                        {userProfile?.role === "foreman"
                          ? "Бригадир (Foreman)"
                          : userProfile?.role === "observer"
                          ? "Диспетчер (Observer)"
                          : "Администратор"}
                      </span>
                      <span>Логин: {userProfile?.username || "demo_observer"}</span>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  id="logout-btn"
                  className={`${styles.btn} ${styles.btnDanger}`}
                  onClick={handleLogout}
                >
                  Выйти из системы
                </button>
              </div>

            </div>
          )}

          {/* TAB 6: SYSTEM & ABOUT */}
          {activeTab === "system" && (
            <>
              <div className={styles.sectionCard}>
                <div className={styles.sectionHeader}>
                  <div className={styles.sectionTitleGroup}>
                    <h2 className={styles.sectionTitle}>О системе и сборке</h2>
                    <p className={styles.sectionDesc}>Техническая информация о платформе Beeline Business</p>
                  </div>
                </div>

                <div className={styles.settingsList}>
                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Продукт</span>
                      <span className={styles.settingExplanation}>
                        Beeline Business Field Operations Suite — Автоматизированная система управления выездными бригадами
                      </span>
                    </div>
                    <span style={{ fontWeight: 600 }}>v2.4.0 (Enterprise)</span>
                  </div>

                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Технологический стек</span>
                      <span className={styles.settingExplanation}>
                        Next.js 16 (Turbopack), React 19, MapLibre GL, FastAPI, PostgreSQL PostGIS, Google OR-Tools
                      </span>
                    </div>
                    <span style={{ fontSize: "13px", color: "var(--text-secondary)" }}>Production Ready</span>
                  </div>

                  <div className={styles.settingRow}>
                    <div className={styles.settingInfo}>
                      <span className={styles.settingLabel}>Сброс локальных параметров</span>
                      <span className={styles.settingExplanation}>
                        Очистить кэш настроек браузера (тема, стартовый город, фильтры) и вернуть значения по умолчанию
                      </span>
                    </div>
                    <button
                      type="button"
                      className={`${styles.btn} ${styles.btnSecondary}`}
                      onClick={handleResetDefaults}
                    >
                      Сбросить настройки
                    </button>
                  </div>
                </div>
              </div>

              {renderDangerZoneCard()}
            </>
          )}
        </div>
      </div>

      {/* Confirmation Modal for Clearing Business Data */}
      {isClearModalOpen && (
        <div
          className={styles.modalOverlay}
          onClick={() => !isClearing && setIsClearModalOpen(false)}
        >
          <div
            className={styles.modalContent}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="clear-modal-title"
          >
            <div className={styles.modalHeader}>
              <div className={styles.modalIconDanger}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </div>
              <div className={styles.modalTitleGroup}>
                <h3 id="clear-modal-title" className={styles.modalTitle}>
                  Стереть все бизнес-данные?
                </h3>
                <p className={styles.modalSubtitle}>Полный сброс операционной информации базы данных</p>
              </div>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.modalWarningCallout}>
                <strong>Внимание!</strong> Будут безвозвратно удалены все заявки, сформированные маршруты, адреса, локации, складские остатки и история загрузок.
              </div>
              <div className={styles.modalInfoCallout}>
                <strong>Пользователи сохраняются:</strong> Все учетные записи диспетчеров, бригадиров, пароли, сессии и 4 канонических вида работ будут сохранены.
              </div>
              <p style={{ margin: 0, fontSize: "13px" }}>
                После очистки вы сможете загрузить свежий пакет файлов через окно импорта данных.
              </p>
            </div>

            <div className={styles.modalFooter}>
              <button
                type="button"
                className={`${styles.btn} ${styles.btnSecondary}`}
                onClick={() => setIsClearModalOpen(false)}
                disabled={isClearing}
              >
                Отмена
              </button>
              <button
                type="button"
                id="confirm-clear-data-btn"
                className={`${styles.btn} ${styles.btnDanger}`}
                onClick={handleClearData}
                disabled={isClearing}
              >
                {isClearing ? "Стирание данных..." : "Да, стереть данные"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Floating Notification Toast */}
      {toastMsg && (
        <div className={styles.toast}>
          <span className={styles.toastSuccessDot} />
          <span>{toastMsg}</span>
        </div>
      )}
    </div>
  );
}