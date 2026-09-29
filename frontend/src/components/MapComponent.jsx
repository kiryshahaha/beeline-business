"use client";

import { Map, Source, Layer, Marker } from "@vis.gl/react-maplibre";
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
import { useTicketRouteLeg } from "@/hooks/useTicketRouteLeg";
import { isTicketUrgent } from "@/utils/ticketUtils";
import styles from "./MapComponent.module.css";
import routeStyles from "./Routes/Routes.module.css";
import { useTheme } from "@/providers/ThemeProvider";

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
  workerRoute = null,
  locationById,
  selectedObject,
  pinnedTicketId = null,
  districtBoundary = null,
  districtBounds = null,
  showDistrictBoundary = true,
  ticketStatusFilter,
  visibleLayers,
  onSelectObject,
  onClearSelection,
  onMapContextMenu,
  isPinPickMode = false,
  onPinPick,
  isDataReady,
}) {
  const { actualTheme } = useTheme();
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

  // 1.1. Интерактивный расчёт маршрута к выбранной пользователем заявке от предыдущей точки
  // Если попап закрыт, но маршрут зафиксирован (pinnedTicketId), маршрут продолжает отображаться на карте!
  const activeTicket = useMemo(() => {
    const id = selectedObject?.type === "ticket" ? selectedObject.id : pinnedTicketId;
    if (!id) return null;
    return tickets.find((t) => t.id === id) || null;
  }, [selectedObject, pinnedTicketId, tickets]);

  const { routeLeg: activeLegRoute, isLoadingRoute } = useTicketRouteLeg(
    activeTicket,
    tickets,
    workers,
    offices,
  );

  const activeLegFeature = useMemo(() => {
    if (!activeLegRoute?.geometry) return null;
    return {
      type: "Feature",
      geometry: activeLegRoute.geometry,
      properties: {
        routeId: "active-leg-route",
        color: "#EA580C", // Яркий контрастный навигационный оранжевый цвет, отлично видимый на светлых картах
        isSelected: true,
        isDimmed: false,
        distanceKm: activeLegRoute.distanceKm,
        durationMin: activeLegRoute.durationMin,
      },
    };
  }, [activeLegRoute]);

  // 2. Сборка FeatureCollection для векторного слоя дорог
  const routesGeoJson = useMemo(() => {
    const features = [];

    if (visibleLayers.routes) {
      const isAnyRouteSelected = selectedObject?.type === "route";

      const lineFeatures = parsedRoutes
        .filter((r) => {
          if (!r.lineGeometry) return false;
          // Если выбран конкретный маршрут — показываем только его
          if (selectedRouteId) return r.id === selectedRouteId;
          // Если выбран конкретный инженер — показываем только его маршруты
          if (selectedObject?.type === "worker") return r.worker_id === selectedObject.id;
          // Если активен район/границы — показываем маршруты, имеющие точки в границах района
          if (districtBounds && r.allCoordinates?.length > 0) {
            const [[minLng, minLat], [maxLng, maxLat]] = districtBounds;
            return r.allCoordinates.some(
              ([lng, lat]) => lng >= minLng && lng <= maxLng && lat >= minLat && lat <= maxLat
            );
          }
          // Не спамим нерелевантными тестовыми маршрутами из базы данных
          return false;
        })
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

      features.push(...lineFeatures);
    }

    // Всегда отрисовываем активный дорожный сегмент к выбранной заявке
    if (activeLegFeature) {
      features.push(activeLegFeature);
    }

    // Всегда отрисовываем дорожный маршрут между задачами выбранного инженера
    if (workerRoute?.geometry) {
      features.push({
        type: "Feature",
        geometry: workerRoute.geometry,
        properties: {
          routeId: workerRoute.id || `worker-route-${workerRoute.workerId}`,
          workerId: workerRoute.workerId,
          color: workerRoute.color || "#FFC800",
          isSelected: true,
          isDimmed: false,
          isWorkerTasksRoute: true,
          distanceKm: workerRoute.distanceKm,
          durationMin: workerRoute.durationMin,
        },
      });
    }

    return {
      type: "FeatureCollection",
      features,
    };
  }, [
    parsedRoutes,
    selectedObject,
    selectedRouteId,
    serverRouteGeoJson,
    visibleLayers.routes,
    activeLegFeature,
    workerRoute,
    districtBounds,
  ]);

  // 3. Подготовка статических объектов (заявки, работники, офисы)
  const mapItems = useMemo(() => {
    const items = [];
    if (visibleLayers.tickets) {
      tickets.forEach((ticket) => {
        if (ticketStatusFilter === "urgent" && !isTicketUrgent(ticket)) return;
        if (ticketStatusFilter === "in_progress" && ticket.status !== "in_progress") return;
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
    // Если выбран офис и есть границы района, камера будет подогнана под границы района
    if (selectedItem.type === "office" && districtBounds) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;
    map.flyTo({
      center: [selectedItem.longitude, selectedItem.latitude],
      zoom: 16,
      duration: 550,
      essential: true,
    });
  }, [mapRef, selectedItem, districtBounds]);

  // Анимация камеры при выборе района или офиса с границами
  useEffect(() => {
    if (!districtBounds) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;

    map.fitBounds(districtBounds, {
      padding: { top: 90, right: 380, bottom: 120, left: 90 },
      maxZoom: 15,
      duration: 650,
    });
  }, [districtBounds, mapRef]);

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

  // Анимация камеры при построении реалистичного маршрута к выбранной заявке
  useEffect(() => {
    if (!activeLegRoute?.geometry) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;

    let coords = [];
    if (activeLegRoute.geometry.type === "LineString") {
      coords = activeLegRoute.geometry.coordinates;
    } else if (activeLegRoute.geometry.type === "MultiLineString") {
      coords = activeLegRoute.geometry.coordinates.flat(1);
    }

    if (coords.length >= 2) {
      const bounds = coords.reduce(
        (result, point) => [
          [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
          [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
        ],
        [[Infinity, Infinity], [-Infinity, -Infinity]],
      );
      map.fitBounds(bounds, {
        padding: { top: 110, right: 380, bottom: 130, left: 110 },
        maxZoom: 15,
        duration: 700,
      });
    }
  }, [activeLegRoute, mapRef]);

  // Анимация камеры при построении маршрута задач инженера
  useEffect(() => {
    if (!workerRoute?.geometry) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;

    let coords = [];
    if (workerRoute.geometry.type === "LineString") {
      coords = workerRoute.geometry.coordinates;
    } else if (workerRoute.geometry.type === "MultiLineString") {
      coords = workerRoute.geometry.coordinates.flat(1);
    }

    if (coords.length >= 2) {
      const bounds = coords.reduce(
        (result, point) => [
          [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
          [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
        ],
        [[Infinity, Infinity], [-Infinity, -Infinity]],
      );
      map.fitBounds(bounds, {
        padding: { top: 100, right: 380, bottom: 130, left: 100 },
        maxZoom: 15,
        duration: 700,
      });
    }
  }, [workerRoute, mapRef]);

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
    if (isPinPickMode) {
      onPinPick?.({ lat: event.lngLat.lat, lng: event.lngLat.lng });
      return;
    }

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
      if (clickedRouteId && String(clickedRouteId).startsWith("worker-route") && workerRoute) {
        setHoveredRoute({
          route: { color: workerRoute.color || "#FFC800" },
          workerName: `Маршрут инженера: ${workerRoute.workerName} (${workerRoute.distanceKm} км · ~${workerRoute.durationMin} мин)`,
          x: event.point.x,
          y: event.point.y,
        });
        const map = mapRef?.current?.getMap?.() || mapRef?.current;
        if (map) map.getCanvas().style.cursor = "pointer";
        return;
      }
      if (clickedRouteId === "active-leg-route" && activeLegRoute) {
        setHoveredRoute({
          route: { color: "#FFC800" },
          workerName: `Маршрут к заявке (${activeLegRoute.distanceKm} км · ~${activeLegRoute.durationMin} мин)`,
          x: event.point.x,
          y: event.point.y,
        });
        const map = mapRef?.current?.getMap?.() || mapRef?.current;
        if (map) map.getCanvas().style.cursor = "pointer";
        return;
      }
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
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100dvh",
        overflow: "hidden",
      }}
      ref={mapRef}
      initialViewState={{ longitude: 35, latitude: 55, zoom: 1 }}
      mapStyle={
        actualTheme === "light"
          ? `https://api.maptiler.com/maps/streets-v2/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`
          : `https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`
      }
      attributionControl={false}
      interactiveLayerIds={
        visibleLayers.routes || activeLegFeature || workerRoute?.geometry ? ["routes-hit-area", "routes-line"] : []
      }
      maxZoom={20}
      minZoom={0}
      maxPitch={75}
      reuseMaps
      keyboard
      hash
      cursor={isPinPickMode ? "crosshair" : undefined}
      onClick={handleMapClick}
      onContextMenu={(e) => {
        if (e.originalEvent) e.originalEvent.preventDefault();
        onMapContextMenu?.({ lat: e.lngLat.lat, lng: e.lngLat.lng });
      }}
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

      {/* 0.1. Границы района при выборе офиса или района */}
      {districtBoundary && showDistrictBoundary && (
        <Source id="district-boundary-source" type="geojson" data={districtBoundary}>
          {/* Полупрозрачная заливка района: благородный сапфировый оттенок, улицы и дома на белой карте остаются кристально четкими */}
          <Layer
            id="district-boundary-fill"
            type="fill"
            paint={{
              "fill-color": "#2563EB",
              "fill-opacity": 0.08,
            }}
          />
          {/* Контрастная темная подложка границы для четкого визуального разделения */}
          <Layer
            id="district-boundary-casing"
            type="line"
            paint={{
              "line-color": "#0F172A",
              "line-width": 4.5,
              "line-opacity": 0.35,
            }}
          />
          {/* Основная яркая пунктирная линия границы */}
          <Layer
            id="district-boundary-line"
            type="line"
            paint={{
              "line-color": "#1D4ED8",
              "line-width": 2.5,
              "line-dasharray": [5, 2.5],
              "line-opacity": 0.95,
            }}
          />
        </Source>
      )}

      {/* 1. Векторные линии маршрутов (Source + Layers) */}
      <RouteLines routesGeoJson={routesGeoJson} />

      {/* 1.1. Индикаторы старта и финиша для активного маршрута к заявке */}
      {activeLegRoute && (
        <>
          {activeLegRoute.origin?.longitude != null && activeLegRoute.origin?.latitude != null && (
            <Marker
              longitude={activeLegRoute.origin.longitude}
              latitude={activeLegRoute.origin.latitude}
              anchor="bottom"
            >
              <div
                style={{
                  background: "rgba(28, 28, 30, 0.94)",
                  color: "#E2E8F0",
                  border: "1.5px solid rgba(255, 255, 255, 0.2)",
                  borderRadius: "10px",
                  padding: "3px 8px",
                  fontSize: "11px",
                  fontWeight: 600,
                  boxShadow: "0 4px 12px rgba(0,0,0,0.5)",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  pointerEvents: "none",
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#94A3B8" }} />
                <span>{activeLegRoute.origin.label}</span>
              </div>
            </Marker>
          )}

          {activeLegRoute.destination?.longitude != null && activeLegRoute.destination?.latitude != null && (
            <Marker
              longitude={activeLegRoute.destination.longitude}
              latitude={activeLegRoute.destination.latitude}
              anchor="top"
            >
              <div
                style={{
                  background: "rgba(28, 28, 30, 0.95)",
                  color: "#FFFFFF",
                  border: "1.5px solid var(--beeline)",
                  borderRadius: "10px",
                  padding: "3px 9px",
                  fontSize: "11px",
                  fontWeight: 600,
                  boxShadow: "0 6px 16px rgba(0, 0, 0, 0.55), 0 0 0 1px rgba(255, 200, 0, 0.3)",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  cursor: "pointer",
                  marginTop: "6px",
                }}
                onClick={() => onSelectObject("ticket", activeLegRoute.destination.id)}
                title="Нажмите, чтобы открыть карточку заявки"
              >
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--beeline)" }} />
                <span>Заявка #{activeLegRoute.destination.id}</span>
                {activeLegRoute.distanceKm && (
                  <span style={{ opacity: 0.75, fontSize: "10px", fontWeight: 500 }}>
                    · {activeLegRoute.distanceKm} км · {activeLegRoute.durationMin} мин
                  </span>
                )}
              </div>
            </Marker>
          )}
        </>
      )}

      {/* 2. Маркеры последовательности визитов (1, 2, 3...) — только для активного маршрута */}
      {visibleLayers.routes && (
        <RouteMarkers
          selectedRoute={selectedRoute}
          selectedObject={selectedObject}
          onSelectStop={handleSelectStop}
        />
      )}
      {workerRoute?.stops && (
        <RouteMarkers
          selectedRoute={workerRoute}
          selectedObject={selectedObject}
          onSelectStop={(route, stop) => {
            if (stop.ticket_id) {
              onSelectObject("ticket", stop.ticket_id);
            }
          }}
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
          workers={workers}
          selectedTicketRoute={selectedTicketRoute}
          activeLegRoute={activeLegRoute}
          isLoadingRoute={isLoadingRoute}
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
            {hoveredRoute.route.route_number != null
              ? `Маршрут #${hoveredRoute.route.route_number || 1} • ${hoveredRoute.workerName} (${hoveredRoute.route.stops?.length || 0} ост. • ${hoveredRoute.route.distanceKm} км)`
              : hoveredRoute.workerName}
          </span>
        </div>
      )}
    </Map>
  );
}
