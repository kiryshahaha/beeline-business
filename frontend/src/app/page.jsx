"use client";

import MapComponent from "@/components/MapComponent";
import Search from "@/components/Search/Search";
import TicketsStatuses from "@/components/TicketsStatuses/TicketsStatuses";
import Notifications from "@/components/Notifications/Notifications";
import Layers from "@/components/Layers/Layers";
import Menu from "@/components/Menu/Menu";
import { useTickets } from "@/hooks/useTickets";
import { useRef, useState } from "react";
import { useOffices } from "@/hooks/useOffices";
import { useLocations } from "@/hooks/useLocations";
import { useUsers } from "@/hooks/useUsers";
import { useRoutes } from "@/hooks/useRoutes";

export default function Home() {
  const mapRef = useRef(null);
  const { tickets, ticketsData } = useTickets({ limit: 100, offset: 0 });
  const { offices, officesData } = useOffices();
  const { users, usersData } = useUsers({ role: "worker" });
  const { routes, routesData } = useRoutes({ limit: 100 });
  const [selectedObject, setSelectedObject] = useState(null);
  const [visibleLayers, setVisibleLayers] = useState({
    tickets: true,
    workers: true,
    offices: true,
    routes: true,
    heatmap: false,
  });
  const [ticketStatusFilter, setTicketStatusFilter] = useState("all");

  const locationIds = [...new Set([
    ...offices.map((item) => item.location_id),
    ...users.map((user) => user.worker_profile?.start_location_id),
  ].filter(Boolean))];
  const locationQueries = useLocations(locationIds);
  const locations = useMemo(
    () => locationQueries.map((query) => query.data).filter(Boolean),
    [locationQueries],
  );
  const locationById = useMemo(
    () => new Map(locations.map((location) => [location.id, location])),
    [locations],
  );
  const officesFullInfo = useMemo(() => {
    return offices
      .map((office) => {
        const location = locationById.get(office.location_id);
        return location ? { ...location, office_id: office.id, office_name: office.name } : null;
      })
      .filter(Boolean);
  }, [offices, locationById]);

  const workersFullInfo = useMemo(() => {
    return users
      .filter((user) => !user.archived_at && user.worker_profile?.start_location_id)
      .map((user) => ({
        ...user,
        location: locationById.get(user.worker_profile.start_location_id),
      }))
      .filter((user) => user.location);
  }, [users, locationById]);



  const locationsError = locationQueries.some((query) => query.isError);

  const selectObject = (type, id, extra = null) => {
    const layer =
      type === "ticket"
        ? "tickets"
        : type === "worker"
          ? "workers"
          : type === "route"
            ? "routes"
            : "offices";
    setSelectedObject({ type, id, ...(extra || {}) });
    setVisibleLayers((current) => ({ ...current, [layer]: true }));
  };

  const handleSelectResult = (result) => {
    if (result.type === "ticket") {
      if (result.raw.location?.longitude == null || result.raw.location?.latitude == null) return false;
      setTicketStatusFilter("all");
      selectObject("ticket", result.raw.id);
      return true;
    }
    if (result.type === "user") {
      const workerRoute = routes.find((r) => r.worker_id === result.raw.id);
      if (workerRoute) {
        selectObject("route", workerRoute.id, {
          route: workerRoute,
          coordinates: result.raw.worker_profile?.start_location_id
            ? [
              locationById.get(result.raw.worker_profile.start_location_id)?.longitude,
              locationById.get(result.raw.worker_profile.start_location_id)?.latitude,
            ].filter(Boolean)
            : null,
        });
        return true;
      }
      if (result.raw.worker_profile?.start_location_id) {
        selectObject("worker", result.raw.id);
        return true;
      }
      return false;
    }
    if (result.type === "brigade") {
      if (!result.raw.office_id) return false;
      selectObject("office", result.raw.office_id);
      return true;
    }
    return true;
  };

  const toggleLayer = (layer) => {
    setVisibleLayers((current) => ({ ...current, [layer]: !current[layer] }));
  };

  const filteredTickets = tickets.filter((ticket) => {
    if (ticketStatusFilter === "urgent") return ticket.status === "planned" && !ticket.assigned_worker_id;
    if (ticketStatusFilter === "completed") return ticket.status === "completed";
    return true;
  });
  const mappedTicketCount = filteredTickets.filter(
    (ticket) => ticket.location?.latitude != null && ticket.location?.longitude != null,
  ).length;

  const routePoints = visibleLayers.routes
    ? routes.flatMap((r) => {
      const pts = [];
      (r.geojson?.features || []).forEach((f) => {
        if (f.geometry?.type === "Point" && Array.isArray(f.geometry.coordinates)) {
          pts.push(f.geometry.coordinates);
        } else if (f.geometry?.type === "LineString" && Array.isArray(f.geometry.coordinates)) {
          f.geometry.coordinates.forEach((c) => pts.push(c));
        } else if (f.geometry?.type === "MultiLineString" && Array.isArray(f.geometry.coordinates)) {
          f.geometry.coordinates.flat(1).forEach((c) => pts.push(c));
        }
      });
      return pts;
    })
    : [];

  const mapPoints = [
    ...(visibleLayers.tickets
      ? filteredTickets.map((ticket) => [ticket.location?.longitude, ticket.location?.latitude])
      : []),
    ...(visibleLayers.workers
      ? workersFullInfo.map((worker) => [worker.location.longitude, worker.location.latitude])
      : []),
    ...(visibleLayers.offices
      ? officesFullInfo.map((office) => [office.longitude, office.latitude])
      : []),
    ...routePoints,
  ];

  const clearSelection = () => setSelectedObject(null);

  return (
    <main style={{ height: "100dvh", position: "relative" }}>
      <div
        style={{
          position: "absolute",
          inset: 22,
          pointerEvents: "none",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          zIndex: 10,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ pointerEvents: "auto" }}>
            <Search onSelectResult={handleSelectResult} />
          </div>
          <div style={{ pointerEvents: "auto" }}>
            <Notifications />
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div style={{ display: "flex", gap: "16px", alignItems: "flex-end", marginLeft: "75px" }}>
            <div style={{ pointerEvents: "auto" }}>
              <Layers
                mapRef={mapRef}
                layers={visibleLayers}
                counts={{
                  tickets: `${mappedTicketCount}/${ticketsData.isLoading ? "…" : filteredTickets.length}`,
                  workers: `${workersFullInfo.length}/${usersData.isLoading ? "…" : users.length}`,
                  offices: `${officesFullInfo.length}/${officesData.isLoading ? "…" : offices.length}`,
                  routes: `${routes.length}/${routesData.isLoading ? "…" : routes.length}`,
                }}
                onToggleLayer={toggleLayer}
                points={mapPoints}
                error={
                  ticketsData.isError ? "Не удалось загрузить заявки"
                    : officesData.isError ? "Не удалось загрузить офисы"
                      : routesData.isError ? "Не удалось загрузить маршруты"
                        : locationsError ? "Не удалось загрузить часть адресов"
                          : null
                }
              />
            </div>
            <div style={{ pointerEvents: "auto" }}>
              <Menu />
            </div>
          </div>
          <div style={{ pointerEvents: "auto" }}>
            <TicketsStatuses
              filter={ticketStatusFilter}
              onFilterChange={setTicketStatusFilter}
              onSelectTicket={(ticket) => {
                setTicketStatusFilter("all");
                selectObject("ticket", ticket.id);
              }}
            />
          </div>
        </div>
      </div>

      <MapComponent
        mapRef={mapRef}
        tickets={tickets}
        offices={officesFullInfo}
        workers={workersFullInfo}
        routes={routes}
        locationById={locationById}
        selectedObject={selectedObject}
        ticketStatusFilter={ticketStatusFilter}
        visibleLayers={visibleLayers}
        onSelectObject={selectObject}
        onClearSelection={clearSelection}
        isDataReady={
          !ticketsData.isLoading
          && !officesData.isLoading
          && !usersData.isLoading
          && !routesData.isLoading
          && locationQueries.every((query) => !query.isLoading)
        }
      />
    </main>
  );
}
