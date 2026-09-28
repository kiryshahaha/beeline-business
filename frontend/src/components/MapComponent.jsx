"use client";

import { Map, Source, Layer } from "@vis.gl/react-maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useMemo, useRef, useState } from "react";
import { ClusterComponent } from "./ClusterComponent";
import OfficePopup from "./OfficePopup";
import TicketPopup from "./Popups/TicketPopup";
import WorkerPopup from "./Popups/WorkerPopup";
import RouteLines from "./Routes/RouteLines";
import RouteMarkers from "./Routes/RouteMarkers";
import RouteFloatingCard from "./Routes/RouteFloatingCard";
import RouteStopPopup from "./Routes/RouteStopPopup";
import { calculateRouteDistanceKm } from "./Routes/routeUtils";
import { useRouteGeoJson } from "@/hooks/useRoutes";
import styles from "./MapComponent.module.css";
import routeStyles from "./Routes/Routes.module.css";

const ROUTE_PALETTE = [
  "#FFB800", // Beeline Gold
  "#00D2BE", // Cyan / Teal
  "#7B61FF", // Purple
  "#FF5252", // Coral
  "#2ED573", // Emerald
  "#1E90FF", // Blue
  "#FFA502", // Amber
  "#A55EEA", // Violet
];

function getRouteColor(workerId, index) {
  const val = Number(workerId || index || 0);
  return ROUTE_PALETTE[Math.abs(val) % ROUTE_PALETTE.length];
}

export default function MapComponent({
  mapRef,
  tickets,
  offices,
  workers,
  routes = [],
  locationById,
  selectedObject,
  ticketStatusFilter,
  visibleLayers,
  onSelectObject,
  onClearSelection,
  isDataReady,
}) {
  const didFitBounds = useRef(false);
  const [hoveredRoute, setHoveredRoute] = useState(null);

  // 1. Подготовка и нормализация маршрутов (поддержка реальных дорожных полилиний LineString/MultiLineString)
  const parsedRoutes = useMemo(() => {
    return (routes || []).map((route, idx) => {
      const color = getRouteColor(route.worker_id, idx);
      const features = route.geojson?.features || [];

      const stops = features
        .filter((f) => f.geometry?.type === "Point" && f.properties?.sequence != null)
        .sort((a, b) => (a.properties.sequence || 0) - (b.properties.sequence || 0))
        .map((f) => ({
          ...f.properties,
          longitude: f.geometry.coordinates[0],
          latitude: f.geometry.coordinates[1],
        }));

      // Реальная геометрия дорог от бэкенда (LineString или MultiLineString)
      const pathFeatures = features.filter(
        (f) =>
          f.geometry?.type === "LineString" ||
          f.geometry?.type === "MultiLineString",
      );

      let lineGeometry = null;
      if (pathFeatures.length > 0) {
        lineGeometry = pathFeatures[0].geometry;
      } else if (stops.length >= 2) {
        lineGeometry = {
          type: "LineString",
          coordinates: stops.map((s) => [s.longitude, s.latitude]),
        };
      }

      let allCoordinates = [];
      if (lineGeometry?.type === "LineString") {
        allCoordinates = lineGeometry.coordinates;
      } else if (lineGeometry?.type === "MultiLineString") {
        allCoordinates = lineGeometry.coordinates.flat(1);
      } else {
        allCoordinates = stops.map((s) => [s.longitude, s.latitude]);
      }

      const distanceKm = calculateRouteDistanceKm({
        allCoordinates,
        stops,
        raw: route,
      });

      return {
        id: route.id,
        worker_id: route.worker_id,
        route_number: route.route_number,
        route_date: route.route_date,
        is_current_plan: route.is_current_plan,
        day_revision: route.day_revision,
        color,
        stops,
        lineGeometry,
        allCoordinates,
        distanceKm,
        raw: route,
      };
    });
  }, [routes]);

  const selectedRouteId = selectedObject?.type === "route" ? selectedObject.id : null;
  const { data: serverRouteGeoJson } = useRouteGeoJson(selectedRouteId);

  // 2. Сборка FeatureCollection для векторного слоя дорог
  const routesGeoJson = useMemo(() => {
    if (!visibleLayers.routes) {
      return { type: "FeatureCollection", features: [] };
    }

    const isAnyRouteSelected = selectedObject?.type === "route";

    const lineFeatures = parsedRoutes
      .filter((r) => r.lineGeometry != null)
      .map((r) => {
        const isSelected = selectedRouteId === r.id;
        const isDimmed = isAnyRouteSelected && !isSelected;

        let geometry = r.lineGeometry;
        if (isSelected && serverRouteGeoJson?.features) {
          const serverLine = serverRouteGeoJson.features.find(
            (f) => f.geometry?.type === "LineString" || f.geometry?.type === "MultiLineString",
          );
          if (serverLine?.geometry) {
            geometry = serverLine.geometry;
          }
        }

        return {
          type: "Feature",
          geometry,
          properties: {
            routeId: r.id,
            workerId: r.worker_id,
            color: r.color,
            isSelected,
            isDimmed,
          },
        };
      });

    return {
      type: "FeatureCollection",
      features: lineFeatures,
    };
  }, [parsedRoutes, selectedObject, selectedRouteId, serverRouteGeoJson, visibleLayers.routes]);

  // 3. Подготовка статических объектов (заявки, работники, офисы)
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
        label: `Инженер: ${[worker.name, worker.surname, worker.lastname].filter(Boolean).join(" ")}`,
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

  // 3.1. Подготовка данных для тепловой карты плотности заявок
  const ticketsHeatmapGeoJson = useMemo(() => {
    if (!visibleLayers.heatmap) {
      return { type: "FeatureCollection", features: [] };
    }
    const features = tickets
      .filter((t) => Number.isFinite(t.location?.latitude) && Number.isFinite(t.location?.longitude))
      .map((t) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [t.location.longitude, t.location.latitude],
        },
        properties: {
          id: t.id,
          priority: t.priority || 3,
        },
      }));
    return { type: "FeatureCollection", features };
  }, [tickets, visibleLayers.heatmap]);

  const selectedItem = mapItems.find(
    (item) => item.type === selectedObject?.type && item.id === selectedObject?.id,
  );

  const selectedRoute = useMemo(() => {
    if (selectedObject?.type !== "route") return null;
    return parsedRoutes.find((r) => r.id === selectedObject.id) || null;
  }, [parsedRoutes, selectedObject]);

  const selectedRouteWorker = useMemo(() => {
    if (!selectedRoute) return null;
    return workers.find((w) => w.id === selectedRoute.worker_id) || null;
  }, [selectedRoute, workers]);

  // Анимация камеры при выборе объекта
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

  // Анимация камеры при выборе маршрута или конкретной остановки
  useEffect(() => {
    if (selectedObject?.type !== "route" || !selectedRoute) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;

    if (selectedObject.stopSequence != null && selectedObject.coordinates) {
      map.flyTo({
        center: selectedObject.coordinates,
        zoom: 16,
        offset: [-100, 0],
        duration: 500,
        essential: true,
      });
      return;
    }

    if (selectedRoute.allCoordinates.length >= 2) {
      const bounds = selectedRoute.allCoordinates.reduce(
        (result, point) => [
          [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
          [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
        ],
        [[Infinity, Infinity], [-Infinity, -Infinity]],
      );
      map.fitBounds(bounds, {
        padding: { top: 90, right: 410, bottom: 120, left: 90 },
        maxZoom: 15,
        duration: 650,
      });
    }
  }, [mapRef, selectedObject, selectedRoute]);

  const handleFocusRoute = (routeToFocus = selectedRoute) => {
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map || !routeToFocus || routeToFocus.allCoordinates.length < 2) return;
    const bounds = routeToFocus.allCoordinates.reduce(
      (result, point) => [
        [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
        [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
      ],
      [[Infinity, Infinity], [-Infinity, -Infinity]],
    );
    map.fitBounds(bounds, {
      padding: { top: 90, right: 410, bottom: 120, left: 90 },
      maxZoom: 15,
      duration: 650,
    });
  };

  // Начальная подгонка камеры под объекты
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

  // Клик по карте (выбор линии маршрута без лишнего попапа-дубля)
  const handleMapClick = (event) => {
    const feature = event.features && event.features[0];
    if (
      feature &&
      (feature.layer?.id === "routes-line" || feature.layer?.id === "routes-hit-area")
    ) {
      const clickedRouteId = feature.properties.routeId;
      const route = parsedRoutes.find((r) => r.id === clickedRouteId);
      if (route) {
        onSelectObject("route", clickedRouteId, {
          route,
        });
        return;
      }
    }
    onClearSelection();
  };

  const handleMouseMove = (event) => {
    const feature = event.features && event.features[0];
    if (
      feature &&
      (feature.layer?.id === "routes-line" || feature.layer?.id === "routes-hit-area")
    ) {
      const clickedRouteId = feature.properties.routeId;
      const route = parsedRoutes.find((r) => r.id === clickedRouteId);
      if (route) {
        const worker = workers.find((w) => w.id === route.worker_id);
        const workerName = worker
          ? [worker.surname, worker.name].filter(Boolean).join(" ")
          : `Инженер #${route.worker_id}`;
        setHoveredRoute({
          route,
          workerName,
          x: event.point.x,
          y: event.point.y,
        });
        const map = mapRef?.current?.getMap?.() || mapRef?.current;
        if (map) map.getCanvas().style.cursor = "pointer";
        return;
      }
    }
    if (hoveredRoute) {
      setHoveredRoute(null);
    }
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (map && map.getCanvas().style.cursor === "pointer") {
      map.getCanvas().style.cursor = "";
    }
  };

  const handleMouseLeave = () => {
    setHoveredRoute(null);
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (map) map.getCanvas().style.cursor = "";
  };

  // Поиск принадлежности заявки к маршруту
  const selectedTicketRoute = useMemo(() => {
    if (selectedItem?.type !== "ticket") return null;
    const r = parsedRoutes.find((route) =>
      route.stops.some((s) => s.ticket_id === selectedItem.id),
    );
    if (!r) return null;
    const stop = r.stops.find((s) => s.ticket_id === selectedItem.id);
    return { route: r, stop };
  }, [parsedRoutes, selectedItem]);

  // Поиск маршрута для выбранного техника
  const selectedWorkerRoute = useMemo(() => {
    if (selectedItem?.type !== "worker") return null;
    return parsedRoutes.find((route) => route.worker_id === selectedItem.id) || null;
  }, [parsedRoutes, selectedItem]);

  // Обработчик выбора остановки из карточки или маркера
  const handleSelectStop = (route, stop) => {
    onSelectObject("route", route.id, {
      route,
      stopSequence: stop.sequence,
      stop,
      coordinates: [stop.longitude, stop.latitude],
    });
  };

  return (
    <Map
      className={styles.map}
      ref={mapRef}
      initialViewState={{ longitude: 35, latitude: 55, zoom: 1 }}
      mapStyle={`https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`}
      attributionControl={false}
      interactiveLayerIds={visibleLayers.routes ? ["routes-hit-area", "routes-line"] : []}
      maxZoom={20}
      minZoom={0}
      maxPitch={75}
      reuseMaps
      keyboard
      hash
      onClick={handleMapClick}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* 0. Слой тепловой карты плотности заявок (Heatmap) */}
      {visibleLayers.heatmap && (
        <Source id="tickets-heatmap-source" type="geojson" data={ticketsHeatmapGeoJson}>
          <Layer
            id="tickets-heatmap-layer"
            type="heatmap"
            maxzoom={15}
            paint={{
              "heatmap-weight": [
                "interpolate",
                ["linear"],
                ["get", "priority"],
                1, 2.0,
                2, 1.5,
                3, 1.0,
              ],
              "heatmap-intensity": [
                "interpolate",
                ["linear"],
                ["zoom"],
                0, 0.8,
                9, 1.5,
                15, 3.0,
              ],
              "heatmap-color": [
                "interpolate",
                ["linear"],
                ["heatmap-density"],
                0, "rgba(0, 0, 0, 0)",
                0.2, "rgba(37, 99, 235, 0.45)",
                0.4, "rgba(6, 182, 212, 0.65)",
                0.6, "rgba(234, 179, 8, 0.75)",
                0.8, "rgba(249, 115, 22, 0.85)",
                1, "rgba(225, 29, 72, 0.95)",
              ],
              "heatmap-radius": [
                "interpolate",
                ["linear"],
                ["zoom"],
                0, 4,
                9, 16,
                15, 28,
              ],
              "heatmap-opacity": 0.82,
            }}
          />
        </Source>
      )}

      {/* 1. Векторные линии маршрутов (Source + Layers) */}
      <RouteLines routesGeoJson={routesGeoJson} />

      {/* 2. Маркеры последовательности визитов (1, 2, 3...) — только для активного маршрута */}
      {visibleLayers.routes && (
        <RouteMarkers
          selectedRoute={selectedRoute}
          selectedObject={selectedObject}
          onSelectStop={handleSelectStop}
        />
      )}

      {/* 3. Кластеризация базовых объектов (заявки, работники, офисы) */}
      <ClusterComponent
        data={mapItems}
        selectedObject={selectedObject}
        onSelectObject={({ type, id }) => onSelectObject(type, id)}
      />

      {/* 4. Информационные окна (Popups) */}
      {selectedItem?.type === "office" && (
        <OfficePopup
          data={selectedItem.data}
          longitude={selectedItem.longitude}
          latitude={selectedItem.latitude}
          onClose={onClearSelection}
        />
      )}

      {selectedItem?.type === "ticket" && (
        <TicketPopup
          ticket={selectedItem.data}
          selectedTicketRoute={selectedTicketRoute}
          onSelectRouteStop={handleSelectStop}
          onClose={onClearSelection}
        />
      )}

      {selectedItem?.type === "worker" && (
        <WorkerPopup
          worker={selectedItem.data}
          selectedWorkerRoute={selectedWorkerRoute}
          onSelectRoute={(route) => {
            onSelectObject("route", route.id, {
              route,
              coordinates: [selectedItem.longitude, selectedItem.latitude],
            });
          }}
          onClose={onClearSelection}
        />
      )}

      {/* 5. Попап клика на конкретную остановку маршрута */}
      {selectedRoute && selectedObject.stop && (
        <RouteStopPopup
          stop={selectedObject.stop}
          totalStops={selectedRoute.stops.length}
          route={selectedRoute.raw}
          worker={selectedRouteWorker}
          ticket={tickets.find((t) => t.id === selectedObject.stop.ticket_id)}
          location={locationById?.get?.(selectedObject.stop.location_id)}
          longitude={selectedObject.coordinates[0]}
          latitude={selectedObject.coordinates[1]}
          onClose={() => {
            // Закрываем только попап конкретной остановки, оставляя сам маршрут активным в панели!
            onSelectObject("route", selectedRoute.id, {
              route: selectedRoute,
            });
          }}
          onSelectNextStop={() => {
            const nextStop = selectedRoute.stops.find(
              (s) => s.sequence === selectedObject.stop.sequence + 1,
            );
            if (nextStop) {
              handleSelectStop(selectedRoute, nextStop);
            }
          }}
          onSelectPrevStop={() => {
            const prevStop = selectedRoute.stops.find(
              (s) => s.sequence === selectedObject.stop.sequence - 1,
            );
            if (prevStop) {
              handleSelectStop(selectedRoute, prevStop);
            }
          }}
        />
      )}

      {/* 6. Интерактивная панель инспектора маршрута (Маршрутный лист) */}
      <RouteFloatingCard
        selectedRoute={selectedRoute}
        allRoutes={parsedRoutes}
        worker={selectedRouteWorker}
        selectedObject={selectedObject}
        tickets={tickets}
        offices={offices}
        locationById={locationById}
        onSelectStop={handleSelectStop}
        onSelectRoute={(newRoute) => {
          onSelectObject("route", newRoute.id, { route: newRoute });
          handleFocusRoute(newRoute);
        }}
        onFocusRoute={handleFocusRoute}
        onClose={onClearSelection}
      />

      {/* 7. Всплывающий тултип при наведении курсора на векторную линию любого маршрута */}
      {hoveredRoute && (
        <div
          className={routeStyles.routeHoverTooltip}
          style={{ left: hoveredRoute.x, top: hoveredRoute.y }}
        >
          <span
            className={routeStyles.routeColorDot}
            style={{ backgroundColor: hoveredRoute.route.color }}
          />
          <span>
            Маршрут #{hoveredRoute.route.route_number || 1} • {hoveredRoute.workerName} ({hoveredRoute.route.stops.length} ост. • {hoveredRoute.route.distanceKm} км)
          </span>
        </div>
      )}
    </Map>
  );
}
