"use client";

import { useState } from "react";
import { Marker } from "@vis.gl/react-maplibre";
import { IconStartFlag, IconFinishFlag } from "../Markers/MapIcons";
import PointTooltip from "../Markers/PointTooltip";
import styles from "./Routes.module.css";

function RouteStopMarkerItem({
  route,
  stop,
  isSelectedStop,
  isStart,
  isFinish,
  onSelectStop,
}) {
  const [isHovered, setIsHovered] = useState(false);

  const tooltipTag = isStart ? "Старт" : isFinish ? "Финиш" : `Ост. ${stop.sequence}`;
  const tooltipText = stop.ticket_id
    ? `Заявка #${stop.ticket_id}`
    : isStart
      ? "База отправления"
      : "База возврата";

  return (
    <div
      className={styles.stopMarkerContainer}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <button
        type="button"
        className={`${styles.routeStopMarker} ${
          isSelectedStop ? styles.routeStop_selected : ""
        } ${isStart ? styles.routeStop_start : ""} ${
          isFinish ? styles.routeStop_finish : ""
        }`}
        style={{
          backgroundColor: route.color,
        }}
        onClick={(e) => {
          e.stopPropagation();
          onSelectStop(route, stop);
        }}
        title={`Маршрут #${route.route_number || 1}, Остановка #${stop.sequence}`}
        aria-label={`Остановка #${stop.sequence}`}
      >
        {isStart ? (
          <IconStartFlag size={11} />
        ) : isFinish ? (
          <IconFinishFlag size={11} />
        ) : (
          stop.sequence
        )}
      </button>

      {isHovered && !isSelectedStop && (
        <PointTooltip
          tag={tooltipTag}
          tagVariant={isStart ? "completed" : isFinish ? "stop" : "planned"}
          text={tooltipText}
          subtext={stop.address}
        />
      )}
    </div>
  );
}

export default function RouteMarkers({
  selectedRoute,
  selectedObject,
  onSelectStop,
}) {
  // Маркеры остановок рендерятся ТОЛЬКО для активно выбранного маршрута.
  // Это предотвращает налипание десятков дублирующих маркеров поверх заявок на общем плане карты.
  if (!selectedRoute) return null;

  return selectedRoute.stops.map((stop) => {
    const isSelectedStop =
      selectedObject?.type === "route" &&
      selectedObject.id === selectedRoute.id &&
      selectedObject.stopSequence === stop.sequence;

    const isStart = stop.sequence === 1 && !stop.ticket_id;
    const isFinish =
      stop.sequence === selectedRoute.stops.length &&
      !stop.ticket_id &&
      selectedRoute.stops.length > 1;

    return (
      <Marker
        key={`route-${selectedRoute.id}-stop-${stop.sequence}`}
        longitude={stop.longitude}
        latitude={stop.latitude}
        anchor="center"
        onClick={(e) => {
          e.originalEvent.stopPropagation();
          onSelectStop(selectedRoute, stop);
        }}
      >
        <RouteStopMarkerItem
          route={selectedRoute}
          stop={stop}
          isSelectedStop={isSelectedStop}
          isStart={isStart}
          isFinish={isFinish}
          onSelectStop={onSelectStop}
        />
      </Marker>
    );
  });
}
