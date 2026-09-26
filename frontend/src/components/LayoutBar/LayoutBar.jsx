"use client"

import React from "react";
import { usePathname, useRouter } from "next/navigation";
import styles from "./LayoutBar.module.css";

const icons = [
  { id: "map", src: "/icons/icon-map.svg", alt: "Map", href: "/" },
  { id: "list", src: "/icons/icon-list.svg", alt: "Dashboard", href: "/dashboard" },
  { id: "settings", src: "/icons/icon-settings.svg", alt: "Settings", href: "/settings" },
];

const LayoutBar = () => {
  const pathname = usePathname();
  const router = useRouter();

  if (pathname === "/login") return null;

  const activeIndex = icons.findIndex(icon => pathname === icon.href);
  const safeIndex = activeIndex === -1 ? 0 : activeIndex;

  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
        <div 
          className={styles.indicator} 
          style={{ transform: `translateY(${safeIndex * 52}px)` }} 
        />
        {icons.map((icon) => (
          <div
            key={icon.id}
            className={`${styles.icon} ${pathname === icon.href ? styles.active : ""}`}
            onClick={() => router.push(icon.href)}
          >
            <div
              className={styles.iconImage}
              style={{
                maskImage: `url(${icon.src})`,
                WebkitMaskImage: `url(${icon.src})`,
              }}
              title={icon.alt}
            />
          </div>
        ))}
      </div>
    </div>
  );
};

export default LayoutBar;