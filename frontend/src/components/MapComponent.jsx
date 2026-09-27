"use client";

import { Map, Popup } from "@vis.gl/react-maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef } from "react";
import { ClusterComponent } from "./ClusterComponent";
import OfficePopup from "./OfficePopup";
import styles from "./MapComponent.module.css";

const STATUS_LABELS = {
  planned: "Ожидает",
  in_progress: "В работе",
  completed: "Выполнена",
  wont_fix: "Отменена",
};

export default function MapComponent({
  mapRef,
  tickets,
  offices,
  workers,
  selectedObject,
  ticketStatusFilter,
  visibleLayers,
  onSelectObject,
  onClearSelection,
  isDataReady,
}) {
  const didFitBounds = useRef(false);
  const mapItems = useMemo(() => {
    const items = [];
    if (visibleLayers.tickets) {
      tickets.forEach((ticket) => {
        if (ticketStatusFilter === "urgent" && (ticket.status !== "planned" || ticket.assigned_worker_id)) return;
        if (ticketStatusFilter === "completed" && ticket.status !== "completed") return;
        items.push({
          id: ticket.id,
          type: "ticket",
          latitude: ticket.location?.latitude,
          longitude: ticket.location?.longitude,
          label: `Заявка #${ticket.id}: ${ticket.title}`,
          data: ticket,
        });
      });
    }
    if (visibleLayers.workers) {
      workers.forEach((worker) => items.push({
        id: worker.id,
        type: "worker",
        latitude: worker.location?.latitude,
        longitude: worker.location?.longitude,
        label: `Точка старта: ${[worker.name, worker.surname, worker.lastname].filter(Boolean).join(" ")}`,
        data: worker,
      }));
    }
    if (visibleLayers.offices) {
      offices.forEach((office) => items.push({
        id: office.office_id,
        type: "office",
        latitude: office.latitude,
        longitude: office.longitude,
        label: office.office_name || `Офис #${office.office_id}`,
        data: office,
      }));
    }
    return items.filter(
      (item) => Number.isFinite(item.longitude) && Number.isFinite(item.latitude),
    );
  }, [offices, tickets, ticketStatusFilter, visibleLayers, workers]);

  const selectedItem = mapItems.find(
    (item) => item.type === selectedObject?.type && item.id === selectedObject?.id,
  );

  useEffect(() => {
    if (!selectedItem) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;
    map.flyTo({
      center: [selectedItem.longitude, selectedItem.latitude],
      zoom: 16,
      duration: 550,
      essential: true,
    });
  }, [mapRef, selectedItem]);

  useEffect(() => {
    if (didFitBounds.current || !isDataReady) return;
    if (window.location.hash.match(/^#\d+(?:\.\d+)?\/-?\d/)) {
      didFitBounds.current = true;
      return;
    }
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map || !mapItems.length) return;
    const coordinates = mapItems.map(({ longitude, latitude }) => [longitude, latitude]);
    const bounds = coordinates.reduce(
      (result, point) => [
        [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
        [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
      ],
      [[Infinity, Infinity], [-Infinity, -Infinity]],
    );
    didFitBounds.current = true;
    map.fitBounds(bounds, {
      padding: {
        top: 90,
        right: Math.min(360, window.innerWidth * 0.2),
        bottom: 170,
        left: Math.min(360, window.innerWidth * 0.2),
      },
      maxZoom: coordinates.length === 1 ? 15 : 13,
      duration: 600,
    });
  }, [isDataReady, mapItems, mapRef]);

  return (
    <Map
      className={styles.map}
      ref={mapRef}
      initialViewState={{ longitude: 35, latitude: 55, zoom: 1 }}
      mapStyle={`https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`}
      attributionControl={false}
      maxZoom={20}
      minZoom={0}
      maxPitch={75}
      reuseMaps
      keyboard
      hash
      onClick={onClearSelection}
    >
      <ClusterComponent
        data={mapItems}
        selectedObject={selectedObject}
        onSelectObject={({ type, id }) => onSelectObject(type, id)}
      />
      {selectedItem?.type === "office" && (
        <OfficePopup
          data={selectedItem.data}
          longitude={selectedItem.longitude}
          latitude={selectedItem.latitude}
          onClose={onClearSelection}
        />
      )}
      {selectedItem?.type === "ticket" && (
        <Popup
          longitude={selectedItem.longitude}
          latitude={selectedItem.latitude}
          closeButton
          closeOnClick={false}
          onClose={onClearSelection}
        >
          <div className={styles.geoPopup}>
            <span className={styles.popupEyebrow}>Заявка #{selectedItem.id}</span>
            <h3>{selectedItem.data.title}</h3>
            <p>{selectedItem.data.location?.address || "Адрес не указан"}</p>
            <p className={styles.coordinates}>{selectedItem.latitude.toFixed(5)}, {selectedItem.longitude.toFixed(5)}</p>
            <div className={styles.popupMeta}>
              <span className={`${styles.status} ${styles[`status_${selectedItem.data.status}`]}`}>
                {STATUS_LABELS[selectedItem.data.status] || selectedItem.data.status}
              </span>
              <span>{selectedItem.data.work_type || "Вид работ не указан"}</span>
            </div>
            {selectedItem.data.visit_window_start && (
              <p className={styles.popupTime}>
                Визит: {new Date(selectedItem.data.visit_window_start).toLocaleString("ru-RU", {
                  day: "numeric",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </p>
            )}
          </div>
        </Popup>
      )}
      {selectedItem?.type === "worker" && (
        <Popup
          longitude={selectedItem.longitude}
          latitude={selectedItem.latitude}
          closeButton
          closeOnClick={false}
          onClose={onClearSelection}
        >
          <div className={styles.geoPopup}>
            <span className={styles.popupEyebrow}>Точка старта техника</span>
            <h3>{[selectedItem.data.name, selectedItem.data.surname, selectedItem.data.lastname].filter(Boolean).join(" ")}</h3>
            <p>{selectedItem.data.location?.address || "Адрес не указан"}</p>
            <p className={styles.coordinates}>{selectedItem.latitude.toFixed(5)}, {selectedItem.longitude.toFixed(5)}</p>
            <div className={styles.popupMeta}>
              <span>{selectedItem.data.brigade_name || "Без бригады"}</span>
              <span>{selectedItem.data.worker_profile?.transport_type || "Транспорт не указан"}</span>
            </div>
          </div>
        </Popup>
      )}
    </Map>
  );
}
