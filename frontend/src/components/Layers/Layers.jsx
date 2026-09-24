"use client";

import Image from "next/image";
import { useState } from "react";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";
import styles from "./Layers.module.css";

const MAP_STYLES = {
  standard: {
    label: "Обычная",
    url: `https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`,
  },
  satellite: {
    label: "Спутник",
    url: `https://api.maptiler.com/maps/019fce77-aa22-7f7d-923a-691e2491e4dd/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`,
  },
  dark: {
    label: "Тёмная",
    url: `https://api.maptiler.com/maps/01a0620c-e3b1-7d64-b992-a04cd0fb9fdc/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`,
  },
};

export default function Layers({ mapRef }) {
  const [activeStyle, setActiveStyle] = useState("standard");
  const getMap = () => mapRef?.current?.getMap?.() || mapRef?.current;

  const setStyle = (id) => {
    const map = getMap();
    if (id === activeStyle || !map) return;
    map.setStyle(MAP_STYLES[id].url, { diff: true });
    setActiveStyle(id);
  };

  return (
    <ExpandableMenu
      className={styles.menu}
      baseSize={56}
      renderHeader={() => (
        <div className={styles.trigger}>
          <Image src="/icons/lauers.svg" alt="Слои" width={19} height={19} />
        </div>
      )}
    >
      <div className={styles.panel}>
        <div className={styles.zoom}>
          <button
            type="button"
            onClick={() => getMap()?.zoomIn()}
            aria-label="Увеличить"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => getMap()?.zoomOut()}
            aria-label="Уменьшить"
          >
            −
          </button>
        </div>

        <div className={styles.styles} aria-label="Стили карты">
          {Object.entries(MAP_STYLES).map(([id, style]) => (
            <button
              type="button"
              className={activeStyle === id ? styles.active : ""}
              onClick={() => setStyle(id)}
              aria-pressed={activeStyle === id}
              key={id}
            >
              {style.label}
              {activeStyle === id && <span>✓</span>}
            </button>
          ))}
        </div>
      </div>
    </ExpandableMenu>
  );
}
