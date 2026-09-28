"use client";

import Image from "next/image";
import { useState } from "react";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";
import styles from "./Layers.module.css";

const DEFAULT_VIEW = {
  center: [35, 55],
  zoom: 1,
  bearing: 0,
  pitch: 0,
};

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

export default function Layers({
  mapRef,
  layers,
  counts,
  onToggleLayer,
  error,
  points = [],
}) {
  const [activeStyle, setActiveStyle] = useState("standard");
  const [isGlobe, setIsGlobe] = useState(false);

  const getMap = () => mapRef?.current?.getMap?.() || mapRef?.current;

  const setStyle = (id) => {
    const map = getMap();
    if (id === activeStyle || !map) return;
    map.setStyle(MAP_STYLES[id].url, { diff: true });
    setActiveStyle(id);
  };

  const toggleProjection = () => {
    const map = getMap();
    if (!map) return;

    const nextProjection = isGlobe ? { type: "mercator" } : { type: "globe" };
    map.setProjection(nextProjection);
    setIsGlobe(!isGlobe);
  };

  const resetCamera = () => {
    const map = getMap();
    if (!map) return;

    const validPoints = points.filter(
      ([longitude, latitude]) => Number.isFinite(longitude) && Number.isFinite(latitude),
    );
    if (validPoints.length) {
      const bounds = validPoints.reduce(
        (result, point) => [
          [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
          [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
        ],
        [[Infinity, Infinity], [-Infinity, -Infinity]],
      );
      map.fitBounds(bounds, {
        padding: { top: 80, right: 70, bottom: 100, left: 70 },
        maxZoom: validPoints.length === 1 ? 15 : 13,
        duration: 600,
      });
      return;
    }

    map.flyTo({
      ...DEFAULT_VIEW,
      duration: 800,
      essential: true,
    });
  };

  return (
    <ExpandableMenu
      className={styles.menu}
      baseSize={46}
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
              {activeStyle === id && (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
            </button>
          ))}
        </div>
        <div className={styles.objectLayers}>
          <p className={styles.sectionLabel}>Объекты на карте</p>
          {[
            ["tickets", "Заявки", counts.tickets, styles.ticketDot],
            ["workers", "Исполнители", counts.workers, styles.workerDot],
            ["offices", "Офисы", counts.offices, styles.officeDot],
            ["routes", "Маршруты", counts.routes, styles.routeDot],
            ["heatmap", "Тепловая карта", layers.heatmap ? "Вкл" : "Выкл", styles.heatmapDot],
          ].map(([id, label, count, dotClass]) => (
            <button
              key={id}
              type="button"
              className={`${styles.layerToggle} ${layers[id] ? styles.layerEnabled : ""}`}
              aria-pressed={layers[id]}
              onClick={() => onToggleLayer(id)}
            >
              <i className={dotClass} />
              <span>{label}</span>
              <span className={styles.layerCount}>{count}</span>
            </button>
          ))}
          <p className={styles.sectionLabel}>Статус заявки</p>
          <div className={styles.statusKey}>
            <span><i className={styles.ticketDot} /> Ожидает</span>
            <span><i className={styles.progressDot} /> В работе</span>
            <span><i className={styles.completedDot} /> Выполнена</span>
            <span><i className={styles.cancelledDot} /> Отменена</span>
            <span><i className={styles.routeLineLegend} /> Маршрут</span>
          </div>
          {error && <p className={styles.mapError}>{error}</p>}
        </div>
        <div className={styles.quickActions}>
          <button
            type="button"
            className={styles.quickAction}
            onClick={toggleProjection}
            aria-label={isGlobe ? "Обычная проекция" : "Глобус"}
          >
            {isGlobe ? "Меркатор" : "Глобус"}
          </button>
          <button
            type="button"
            className={styles.quickAction}
            onClick={resetCamera}
            aria-label={points.length ? "Показать все объекты на карте" : "Сбросить приближение и угол обзора"}
          >
            Все объекты
          </button>
        </div>
      </div>
    </ExpandableMenu>
  );
}
