// frontend/src/app/worker/layout.jsx
"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/providers/AuthProvider";
import { useWorkerWS } from "@/hooks/worker/useWorkerWS";
import WorkerNav, { WORKER_NAV_ITEMS } from "@/components/worker/WorkerNav";
import ToastContainer from "@/components/worker/ToastContainer";
import WorkerNotificationsDrawer from "@/components/worker/WorkerNotificationsDrawer";
import styles from "./layout.module.css";

export default function WorkerLayout({ children }) {
  const { user, role, loading, token } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [notifDrawerOpen, setNotifDrawerOpen] = useState(false);

  const { toasts, removeToast, unreadCount, clearUnreadCount } = useWorkerWS();

  const isMapPage = pathname === "/worker/map";

  // Guard against non-workers
  React.useEffect(() => {
    if (!loading) {
      if (!token) {
        router.replace("/login");
      } else if (role && role !== "worker") {
        router.replace("/");
      }
    }
  }, [loading, token, role, router]);

  if (loading || !token || (role && role !== "worker")) {
    return (
      <div className={styles.loadingScreen}>
        <div className={styles.spinner} />
        <span className={styles.loadingText}>Загрузка приложения исполнителя...</span>
      </div>
    );
  }

  const handleOpenNotifs = () => {
    clearUnreadCount();
    setNotifDrawerOpen(true);
  };

  return (
    <div className={styles.appShell}>
      {/* Adaptive Header */}
      <header className={styles.header}>
        <div className={styles.headerContainer}>
          <div className={styles.headerLeft}>
            <div className={styles.logoCircle}>
              <div className={styles.logoBeeline} />
            </div>
            <div className={styles.headerTitle}>
              <span className={styles.brand}>Билайн Бизнес</span>
              <span className={styles.appSub}>Приложение инженера</span>
            </div>
          </div>

          {/* Desktop Navigation Links */}
          <nav className={styles.desktopNav} aria-label="Основная навигация">
            {WORKER_NAV_ITEMS.map((item) => {
              const isActive = item.exact
                ? pathname === item.href
                : pathname.startsWith(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`${styles.desktopNavLink} ${isActive ? styles.desktopNavActive : ""}`}
                >
                  <span className={styles.desktopNavIcon}>{item.icon}</span>
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Header Right */}
          <div className={styles.headerRight}>
            {user && (
              <div className={styles.workerBadge}>
                <span className={styles.workerStatusDot} />
                <span className={styles.workerName}>
                  {user.name} {user.surname?.[0]}.
                </span>
              </div>
            )}

            <button
              type="button"
              className={styles.bellBtn}
              onClick={handleOpenNotifs}
              title="Уведомления"
              aria-label="Уведомления"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              </svg>
              {unreadCount > 0 && (
                <span className={styles.bellBadge}>{unreadCount > 9 ? "9+" : unreadCount}</span>
              )}
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className={`${styles.mainContent} ${isMapPage ? styles.mainContentMap : ""}`}>
        <div className={`${styles.contentContainer} ${isMapPage ? styles.contentContainerMap : ""}`}>
          {children}
        </div>
      </main>

      {/* Mobile Bottom Navigation (auto-hidden on >=768px) */}
      <WorkerNav />

      {/* Floating Real-time Notifications */}
      <ToastContainer toasts={toasts} onRemove={removeToast} />

      {/* History Drawer */}
      <WorkerNotificationsDrawer
        isOpen={notifDrawerOpen}
        onClose={() => setNotifDrawerOpen(false)}
      />
    </div>
  );
}
