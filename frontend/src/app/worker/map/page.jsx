// frontend/src/app/worker/map/page.jsx
"use client";

import React, { useState, useMemo, useRef, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Map, Source, Layer, Marker } from "@vis.gl/react-maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { useAuth } from "@/providers/AuthProvider";
import { useMyDay } from "@/hooks/worker/useMyDay";
import { useWorkerRoutes } from "@/hooks/worker/useWorkerRoutes";
import { getTodayMsk, formatMskTime } from "@/lib/worker/time";
import { getTicketStateBadge } from "@/lib/worker/labels";
import styles from "./map.module.css";

const MAPTILER_KEY = process.env.NEXT_PUBLIC_MAPTILER_API_KEY || "GgqQJqVNCH4XkEWcVnJs";
const MAP_STYLE = `https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${MAPTILER_KEY}`;

function WorkerMapContent() {
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const mapRef = useRef(null);
  const todayMsk = getTodayMsk();

  const { data: dayData, isLoading: isDayLoading } = useMyDay(todayMsk);
  const { currentRoute, isLoading: isRouteLoading } = useWorkerRoutes(user?.id, todayMsk);

  const [selectedTicketId, setSelectedTicketId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [roadLineGeoJson, setRoadLineGeoJson] = useState(null);

  const tickets = useMemo(() => dayData?.tickets || [], [dayData?.tickets]);
  const currentTicketId = dayData?.current_ticket_id;
  const nextTicketId = dayData?.next_ticket_id;

  // Extract stops and static line from route geojson, or fallback to tickets
  const { stops, backendLineGeoJson } = useMemo(() => {
    if (currentRoute?.geojson?.features) {
      const feats = currentRoute.geojson.features;
      const stopFeats = feats.filter((f) => f.geometry?.type === "Point");
      const pathFeats = feats.filter(
        (f) => f.geometry?.type === "LineString" || f.geometry?.type === "MultiLineString"
      );

      const parsedStops = stopFeats.map((sf) => {
        const tId = sf.properties?.ticket_id;
        const matchedTicket = tickets.find((t) => t.id === tId);
        return {
          sequence: sf.properties?.sequence,
          ticketId: tId,
          arrivalAt: sf.properties?.arrival_at,
          coordinates: sf.geometry.coordinates,
          ticket: matchedTicket || {
            id: tId,
            title: `Заявка №${tId}`,
            state: "assigned",
            sequence: sf.properties?.sequence,
          },
        };
      });

      // Sort by sequence
      parsedStops.sort((a, b) => (a.sequence || 999) - (b.sequence || 999));

      let lineData = null;
      if (pathFeats.length > 0) {
        lineData = {
          type: "FeatureCollection",
          features: pathFeats,
        };
      }

      return {
        stops: parsedStops,
        backendLineGeoJson: lineData,
      };
    }

    // Fallback: build stops from tickets with valid coordinates
    const fallbackStops = tickets
      .filter((t) => {
        const lat = t.location?.latitude ?? t.latitude;
        const lon = t.location?.longitude ?? t.longitude;
        return lat != null && lon != null;
      })
      .map((t, idx) => ({
        sequence: t.sequence || idx + 1,
        ticketId: t.id,
        arrivalAt: t.planned_arrival_at,
        coordinates: [
          t.location?.longitude ?? t.longitude,
          t.location?.latitude ?? t.latitude,
        ],
        ticket: t,
      }));

    // Sort fallback stops by sequence
    fallbackStops.sort((a, b) => (a.sequence || 999) - (b.sequence || 999));

    return {
      stops: fallbackStops,
      backendLineGeoJson: null,
    };
  }, [currentRoute, tickets]);

  const effectiveLineGeoJson = backendLineGeoJson || roadLineGeoJson;

  // Ensure route line is ALWAYS constructed and rendered
  useEffect(() => {
    if (backendLineGeoJson || stops.length < 2) {
      return;
    }

    let isCancelled = false;

    async function buildDrivingRoute() {
      try {
        const coordsStr = stops.map((s) => `${s.coordinates[0]},${s.coordinates[1]}`).join(";");
        const res = await fetch(
          `https://router.project-osrm.org/route/v1/driving/${coordsStr}?overview=full&geometries=geojson`
        );
        if (res.ok) {
          const data = await res.json();
          if (!isCancelled && data.code === "Ok" && data.routes?.[0]?.geometry) {
            setRoadLineGeoJson({
              type: "FeatureCollection",
              features: [
                {
                  type: "Feature",
                  geometry: data.routes[0].geometry,
                  properties: {
                    distance: data.routes[0].distance,
                    duration: data.routes[0].duration,
                  },
                },
              ],
            });
            return;
          }
        }
      } catch {
        // fallback to direct line
      }

      if (!isCancelled) {
        setRoadLineGeoJson({
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: {
                type: "LineString",
                coordinates: stops.map((s) => s.coordinates),
              },
              properties: {},
            },
          ],
        });
      }
    }

    buildDrivingRoute();
    return () => {
      isCancelled = true;
    };
  }, [stops, backendLineGeoJson]);

  // Handle ?ticket_id= from URL (e.g. redirected from ticket details)
  const ticketIdParam = searchParams.get("ticket_id");
  const activeTicketId = selectedTicketId !== null ? selectedTicketId : (ticketIdParam ? Number(ticketIdParam) : null);
  const selectedTicket = useMemo(() => {
    if (!activeTicketId) return null;
    const matched = stops.find((s) => s.ticketId === activeTicketId);
    return matched ? matched.ticket : null;
  }, [activeTicketId, stops]);

  useEffect(() => {
    if (ticketIdParam && stops.length > 0) {
      const targetId = Number(ticketIdParam);
      const matched = stops.find((s) => s.ticketId === targetId);
      if (matched && mapRef.current && matched.coordinates) {
        mapRef.current.flyTo({
          center: matched.coordinates,
          zoom: 15,
          duration: 1000,
        });
      }
    }
  }, [ticketIdParam, stops]);

  // Fit bounds when stops are loaded (if no ticket_id param)
  useEffect(() => {
    if (!ticketIdParam && stops.length > 0 && mapRef.current) {
      const lons = stops.map((s) => s.coordinates[0]);
      const lats = stops.map((s) => s.coordinates[1]);
      const minLon = Math.min(...lons);
      const maxLon = Math.max(...lons);
      const minLat = Math.min(...lats);
      const maxLat = Math.max(...lats);

      if (minLon !== maxLon || minLat !== maxLat) {
        mapRef.current.fitBounds(
          [
            [minLon, minLat],
            [maxLon, maxLat],
          ],
          { padding: 70, maxZoom: 15, duration: 1000 }
        );
      } else {
        mapRef.current.flyTo({ center: [minLon, minLat], zoom: 14 });
      }
    }
  }, [stops, ticketIdParam]);

  const handleSelectStop = (stop) => {
    setSelectedTicketId(stop.ticketId);
    if (mapRef.current && stop.coordinates) {
      mapRef.current.flyTo({ center: stop.coordinates, zoom: 15, duration: 800 });
    }
  };

  const defaultCenter = [30.3158, 59.939]; // Default SPb / Moscow

  if (isDayLoading || isRouteLoading) {
    return (
      <div className={styles.loadingContainer}>
        <div className={styles.spinner} />
        <span>Загрузка карты и маршрута...</span>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {/* Main Split Layout: Stops Sidebar on Desktop + Map */}
      <div className={styles.splitLayout}>
        {/* Desktop Sidebar with stops list */}
        <aside className={`${styles.desktopSidebar} ${sidebarOpen ? "" : styles.sidebarCollapsed}`}>
          <div className={styles.sidebarHeader}>
            <div className={styles.sidebarHeaderTop}>
              <div className={styles.sidebarTitleRow}>
                <h2 className={styles.sidebarTitle}>Маршрут дня</h2>
                <span className={styles.stopsCountBadge}>{stops.length} ост.</span>
              </div>
              <button
                type="button"
                className={styles.collapseSidebarBtn}
                onClick={() => setSidebarOpen(false)}
                title="Свернуть панель"
                aria-label="Свернуть панель"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            </div>
            <span className={styles.sidebarSub}>Порядок остановок на сегодня</span>
          </div>

          <div className={styles.stopsList}>
            {stops.length === 0 ? (
              <div className={styles.noStops}>Точки маршрута не назначены</div>
            ) : (
              stops.map((stop) => {
                const isCurrent = stop.ticketId === currentTicketId;
                const isSelected = selectedTicket?.id === stop.ticketId;
                const stateBadge = getTicketStateBadge(stop.ticket);

                const lat = stop.ticket?.location?.latitude ?? stop.coordinates[1];
                const lon = stop.ticket?.location?.longitude ?? stop.coordinates[0];
                const yandexUrl = `https://yandex.ru/maps/?rtext=~${lat},${lon}&rtt=auto`;

                return (
                  <div
                    key={stop.sequence || stop.ticketId}
                    className={`${styles.stopItem} ${isCurrent ? styles.stopCurrent : ""} ${isSelected ? styles.stopSelected : ""}`}
                    onClick={() => handleSelectStop(stop)}
                  >
                    <div className={styles.stopNumBadge}>№{stop.sequence}</div>
                    <div className={styles.stopContent}>
                      <div className={styles.stopTopRow}>
                        <span className={styles.stopItemTitle}>{stop.ticket?.title}</span>
                        <span
                          className={styles.stopBadge}
                          style={{
                            background: stateBadge.color.bg,
                            color: stateBadge.color.text,
                          }}
                        >
                          {stateBadge.label}
                        </span>
                      </div>
                      <div className={styles.stopAddress}>
                        {stop.ticket?.location?.address || stop.ticket?.address || "Адрес не указан"}
                      </div>
                      <div className={styles.stopBottomMeta}>
                        {stop.arrivalAt && (
                          <span className={styles.stopArrival}>
                            Прибытие: <strong>{formatMskTime(stop.arrivalAt)}</strong>
                          </span>
                        )}
                        <div className={styles.stopActionLinks} onClick={(e) => e.stopPropagation()}>
                          <Link href={`/worker/tickets/${stop.ticketId}`} className={styles.stopLink}>
                            К заявке →
                          </Link>
                          <a
                            href={yandexUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={styles.stopYandexLink}
                            title="Открыть маршрут в Яндекс.Картах"
                          >
                            Яндекс
                          </a>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* Button to re-open sidebar when collapsed */}
        {!sidebarOpen && (
          <button
            type="button"
            className={styles.expandSidebarBtn}
            onClick={() => setSidebarOpen(true)}
            title="Открыть список остановок"
            aria-label="Открыть список остановок"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
            <span>Остановки ({stops.length})</span>
          </button>
        )}

        {/* Map Container */}
        <div className={styles.mapWrap}>
          <Map
            ref={mapRef}
            initialViewState={{
              longitude: stops[0]?.coordinates[0] || defaultCenter[0],
              latitude: stops[0]?.coordinates[1] || defaultCenter[1],
              zoom: 11,
            }}
            mapStyle={MAP_STYLE}
            attributionControl={false}
            style={{ width: "100%", height: "100%" }}
          >
            {/* Real driving route path line */}
            {effectiveLineGeoJson && (
              <Source id="route-path-source" type="geojson" data={effectiveLineGeoJson}>
                {/* Dark casing for crisp contrast */}
                <Layer
                  id="route-line-casing"
                  type="line"
                  paint={{
                    "line-color": "#111827",
                    "line-width": 6,
                    "line-opacity": 0.85,
                  }}
                />
                {/* Yellow route line */}
                <Layer
                  id="route-line-core"
                  type="line"
                  paint={{
                    "line-color": "#ffc800",
                    "line-width": 3.5,
                    "line-cap": "round",
                    "line-join": "round",
                  }}
                />
              </Source>
            )}

            {/* Markers for stops */}
            {stops.map((stop) => {
              const isCurrent = stop.ticketId === currentTicketId;
              const isNext = stop.ticketId === nextTicketId;
              const isSelected = selectedTicket?.id === stop.ticketId;

              return (
                <Marker
                  key={stop.sequence || stop.ticketId}
                  longitude={stop.coordinates[0]}
                  latitude={stop.coordinates[1]}
                  anchor="bottom"
                  onClick={(e) => {
                    e.originalEvent.stopPropagation();
                    handleSelectStop(stop);
                  }}
                >
                  <div
                    className={`${styles.markerPin} ${isCurrent ? styles.currentPin : ""} ${isNext ? styles.nextPin : ""} ${isSelected ? styles.selectedPin : ""}`}
                  >
                    <span className={styles.markerNum}>№{stop.sequence}</span>
                  </div>
                </Marker>
              );
            })}
          </Map>

          {/* Bottom Card for selected marker */}
          {selectedTicket && (
            <div className={styles.bottomCard}>
              <button
                type="button"
                className={styles.closeCardBtn}
                onClick={() => setSelectedTicketId(null)}
                aria-label="Закрыть"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
              <div className={styles.cardSeqRow}>
                {selectedTicket.sequence && (
                  <span className={styles.cardSeq}>Остановка №{selectedTicket.sequence}</span>
                )}
                <span className={styles.cardState}>{getTicketStateBadge(selectedTicket).label}</span>
              </div>
              <div className={styles.cardTitle}>{selectedTicket.title}</div>
              <div className={styles.cardAddress}>
                {selectedTicket.location?.address || selectedTicket.address || "Адрес не указан"}
              </div>
              {selectedTicket.planned_arrival_at && (
                <div className={styles.cardTime}>
                  Плановое прибытие: <strong>{formatMskTime(selectedTicket.planned_arrival_at)}</strong>
                </div>
              )}
              <div className={styles.cardActionsRow}>
                <Link
                  href={`/worker/tickets/${selectedTicket.id}`}
                  className={styles.openTicketBtn}
                >
                  Открыть карточку
                </Link>
                {selectedTicket.location?.latitude != null && (
                  <a
                    href={`https://yandex.ru/maps/?rtext=~${selectedTicket.location.latitude},${selectedTicket.location.longitude}&rtt=auto`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className={styles.yandexRouteBtn}
                  >
                    Яндекс
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function WorkerMapPage() {
  return (
    <Suspense fallback={
      <div className={styles.loadingContainer}>
        <div className={styles.spinner} />
        <span>Загрузка карты...</span>
      </div>
    }>
      <WorkerMapContent />
    </Suspense>
  );
}
