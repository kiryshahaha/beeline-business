"use client"

import React from "react";
import { usePathname, useRouter } from "next/navigation";
import styles from "./LayoutBar.module.css";

const icons = [
  { id: "map", src: "/icons/icon-map.svg", alt: "Карта", href: "/" },
  { id: "list", src: "/icons/icon-list.svg", alt: "Заявки", href: "/dashboard" },
  { id: "dispatch", src: "/icons/icon-dispatch.svg", alt: "Распределение", href: "/dispatch" },
  { id: "settings", src: "/icons/icon-settings.svg", alt: "Настройки", href: "/settings" },
];

const LayoutBar = () => {
  const pathname = usePathname();
  const router = useRouter();

  if (pathname === "/login" || pathname?.startsWith("/worker")) return null;

  const activeIndex = icons.findIndex(icon => pathname === icon.href);
  const safeIndex = activeIndex === -1 ? 0 : activeIndex;

  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
        {activeIndex !== -1 && (
          <div 
            className={styles.indicator} 
            style={{ transform: `translateY(${safeIndex * 52}px)` }} 
          />
        )}
        {icons.map((icon) => (
          <button
            key={icon.id}
            type="button"
            className={`${styles.icon} ${pathname === icon.href ? styles.active : ""}`}
            onClick={() => router.push(icon.href)}
            title={icon.alt}
            aria-label={icon.alt}
          >
            <div
              className={styles.iconImage}
              style={{
                maskImage: `url(${icon.src})`,
                WebkitMaskImage: `url(${icon.src})`,
              }}
            />
          </button>
        ))}
      </div>
    </div>
  );
};

export default LayoutBar;