"use client"

import React, { useState } from "react";
import { usePathname } from "next/navigation";
import Menu from "../Menu/Menu";
import styles from "./LayoutBar.module.css";

const icons = [
  { id: "map", src: "/icons/icon-map.svg", alt: "Map" },
  { id: "list", src: "/icons/icon-list.svg", alt: "List" },
  { id: "settings", src: "/icons/icon-settings.svg", alt: "Settings" },
];

const LayoutBar = () => {
  const [activeIcon, setActiveIcon] = useState("map");
  const activeIndex = icons.findIndex(icon => icon.id === activeIcon);
  const pathname = usePathname();

  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
      <div 
        className={styles.indicator} 
        style={{ transform: `translateY(${activeIndex * 52}px)` }} 
      />
      {icons.map((icon) => (
        <div
          key={icon.id}
          className={`${styles.icon} ${activeIcon === icon.id ? styles.active : ""}`}
          onClick={() => setActiveIcon(icon.id)}
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
      {pathname === "/" && <Menu />}
    </div>
  );
};

export default LayoutBar;