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

const CloseIcon = ({ size = 11 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const RouteIcon = ({ size = 13 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="6" cy="19" r="3" />
    <path d="M9 19h8.5a4.5 4.5 0 0 0 0-9H7a4 4 0 0 1 0-8h11" />
  </svg>
);

export default function Layers({
  mapRef,
  layers,
  counts,
  onToggleLayer,
  error,
  points = [],
  activeDistrict = null,
  focusedOffice = null,
  showDistrictBoundary = true,
  onToggleDistrictBoundary = null,
  filterTicketsByDistrict = true,
  onToggleFilterTicketsByDistrict = null,
  activeRouteTicket = null,
  onClearRoute = null,
  onFitDistrict = null,
  onClearDistrict = null,
}) {
  const [activeStyle, setActiveStyle] = useState("standard");
  const [isGlobe, setIsGlobe] = useState(false);

  const hasActiveFocus = Boolean(activeDistrict || focusedOffice || activeRouteTicket);

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
      direction="up"
      className={styles.menu}
      baseSize={46}
      renderHeader={({ isOpen }) => (
        <div
          className={`${styles.trigger} ${isOpen ? styles.triggerOpen : ""}`}
          style={{ position: "relative" }}
          title={isOpen ? "Свернуть" : "Слои карты"}
        >
          <div className={styles.triggerIcon} aria-label="Слои" />
          {hasActiveFocus && !isOpen && <span className={styles.activeBadgeDot} />}
        </div>
      )}
    >
      <div className={styles.panel}>
        {/* Активный фокус района / офиса */}
        {(activeDistrict || focusedOffice) && (
          <div className={styles.districtSection}>
            <div className={styles.districtHeader}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <p className={styles.sectionLabel} style={{ marginBottom: 2 }}>Фокус района</p>
                <div className={styles.districtTitle}>
                  <span className={focusedOffice ? styles.officeIndicator : styles.districtIndicator} />
                  <span className={styles.districtTitleText}>
                    {focusedOffice ? focusedOffice.office_name : activeDistrict}
                  </span>
                </div>
                {focusedOffice?.district && focusedOffice.district !== focusedOffice.office_name && (
                  <div className={styles.districtSub}>{focusedOffice.district}</div>
                )}
              </div>
              {onClearDistrict && (
                <button
                  type="button"
                  className={styles.districtBtnReset}
                  onClick={onClearDistrict}
                  title="Сбросить фокус района"
                  aria-label="Сбросить фокус"
                >
                  <CloseIcon size={11} />
                </button>
              )}
            </div>

            <div className={styles.districtActions}>
              {onFitDistrict && (
                <button
                  type="button"
                  className={styles.districtBtn}
                  onClick={onFitDistrict}
                  title="Приблизить камеру к границам района"
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                  <span>Вписать</span>
                </button>
              )}

              {onToggleFilterTicketsByDistrict && (
                <button
                  type="button"
                  className={`${styles.districtBtn} ${filterTicketsByDistrict ? styles.active : ""}`}
                  onClick={onToggleFilterTicketsByDistrict}
                  title={filterTicketsByDistrict ? "Показать все заявки города" : "Оставить только заявки района"}
                >
                  <span>{filterTicketsByDistrict ? "Только район" : "Все заявки"}</span>
                </button>
              )}
            </div>
          </div>
        )}

        {/* Активный маршрут к заявке */}
        {activeRouteTicket && (
          <div className={styles.routeLegItem}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: 0 }}>
              <span className={styles.routeLegIconWrapper}>
                <RouteIcon size={13} />
              </span>
              <span className={styles.routeLegTitle}>Маршрут к заявке #{activeRouteTicket.id}</span>
            </div>
            {onClearRoute && (
              <button
                type="button"
                className={styles.routeLegClose}
                onClick={onClearRoute}
                title="Скрыть маршрут"
              >
                <CloseIcon size={11} />
              </button>
            )}
          </div>
        )}

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
          <p className={styles.sectionLabel}>Стиль карты</p>
          <div className={styles.styleButtonsRow}>
            {Object.entries(MAP_STYLES).map(([id, style]) => (
              <button
                type="button"
                className={`${styles.styleBtn} ${activeStyle === id ? styles.active : ""}`}
                onClick={() => setStyle(id)}
                aria-pressed={activeStyle === id}
                key={id}
              >
                {style.label}
              </button>
            ))}
          </div>
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

          {activeDistrict && onToggleDistrictBoundary && (
            <button
              type="button"
              className={`${styles.layerToggle} ${showDistrictBoundary ? styles.layerEnabled : ""}`}
              aria-pressed={showDistrictBoundary}
              onClick={onToggleDistrictBoundary}
            >
              <i className={styles.districtDot} />
              <span>Границы района</span>
              <span className={styles.layerCount}>{showDistrictBoundary ? "Вкл" : "Скрыты"}</span>
            </button>
          )}

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
