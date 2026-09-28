"use client";

import MapComponent from "@/components/MapComponent";
import Search from "@/components/Search/Search";
import TicketsStatuses from "@/components/TicketsStatuses/TicketsStatuses";
import Notifications from "@/components/Notifications/Notifications";
import Layers from "@/components/Layers/Layers";
import Menu from "@/components/Menu/Menu";
import { useTickets } from "@/hooks/useTickets";
import { useEffect, useMemo, useRef, useState } from "react";
import { useOffices } from "@/hooks/useOffices";
import { useLocations } from "@/hooks/useLocations";
import { useUsers } from "@/hooks/useUsers";
import { useRoutes } from "@/hooks/useRoutes";
import { useWorkerTasksRoute } from "@/hooks/useWorkerTasksRoute";
import { useBrigades } from "@/hooks/useBrigades";

export default function Home() {
  const mapRef = useRef(null);
  const { tickets, ticketsData } = useTickets({ limit: 100, offset: 0 });
  const { offices, officesData } = useOffices();
  const { users, usersData } = useUsers({ role: "worker" });
  const { brigades = [] } = useBrigades();
  const { routes, routesData } = useRoutes({ limit: 100 });
  const [selectedObject, setSelectedObject] = useState(null);
  const [visibleLayers, setVisibleLayers] = useState({
    tickets: true,
    workers: true,
    offices: true,
    routes: false,
    heatmap: false,
  });
  const [selectedBrigade, setSelectedBrigade] = useState(null);
  const [selectedWorker, setSelectedWorker] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTarget, setSearchTarget] = useState(null);
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

  const brigadeById = useMemo(() => new Map(brigades.map((b) => [b.id, b])), [brigades]);
  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);

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
      setSearchTarget({ type: "ticket", id: result.raw.id, title: result.title, raw: result.raw });
      setSearchQuery(result.title);
      // При выборе заявки остальные не исчезают, а камера перемещается на неё и открывается попап
      setSelectedBrigade(null);
      setSelectedWorker(null);
      setTicketStatusFilter("all");
      selectObject("ticket", result.raw.id);
      return true;
    }

    if (result.type === "user") {
      setSearchTarget({ type: "user", id: result.raw.id, title: result.title, raw: result.raw });
      setSearchQuery(result.title);
      setSelectedWorker(result.raw);
      setSelectedBrigade(null);
      setSelectedObject(null);
      return true;
    }

    if (result.type === "brigade") {
      setSearchTarget({ type: "brigade", id: result.raw.id, title: result.title, raw: result.raw });
      setSearchQuery(result.title);
      setSelectedBrigade(result.raw);
      setSelectedWorker(null);
      setSelectedObject(null);
      return true;
    }

    return true;
  };

  const handleSearchChange = (newQuery) => {
    setSearchQuery(newQuery);
    if (!newQuery.trim()) {
      setSearchTarget(null);
      setSelectedBrigade(null);
      setSelectedWorker(null);
    } else if (searchTarget && newQuery !== searchTarget.title) {
      setSearchTarget(null);
      setSelectedBrigade(null);
      setSelectedWorker(null);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery("");
    setSearchTarget(null);
    setSelectedBrigade(null);
    setSelectedWorker(null);
  };

  const toggleLayer = (layer) => {
    setVisibleLayers((current) => ({ ...current, [layer]: !current[layer] }));
  };

  // 3.1. Фильтрация тасок по выбранному воркеру, бригаде или поисковому запросу
  const displayedTickets = useMemo(() => {
    // Если выбран инженер (через меню или поиск) -> показываем ТОЛЬКО его таски
    if (selectedWorker) {
      return tickets.filter((t) => t.assigned_worker_id === selectedWorker.id);
    }

    // Если выбрана бригада (через меню или поиск) -> показываем ТОЛЬКО её таски
    if (selectedBrigade) {
      const brigadeWorkerIds = new Set(selectedBrigade.worker_ids || []);
      users.forEach((u) => {
        if (u.worker_profile?.brigade_id === selectedBrigade.id) {
          brigadeWorkerIds.add(u.id);
        }
      });

      return tickets.filter((t) => {
        if (t.brigade_id != null && Number(t.brigade_id) === Number(selectedBrigade.id)) {
          return true;
        }
        if (t.assigned_worker_id != null && brigadeWorkerIds.has(t.assigned_worker_id)) {
          return true;
        }
        return false;
      });
    }

    // Если в поиске выбрана конкретная заявка — все остальные НЕ исчезают
    if (searchTarget?.type === "ticket") {
      return tickets;
    }

    // Фильтрация вывода тасок под условия ввода в поиске
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      const qClean = q.replace(/^#/, "");
      return tickets.filter((t) => {
        if (String(t.id).includes(qClean)) return true;
        if (t.title && t.title.toLowerCase().includes(q)) return true;
        if (t.description && t.description.toLowerCase().includes(q)) return true;
        const address = t.location?.address || t.address || "";
        if (address.toLowerCase().includes(q)) return true;
        if (t.assigned_worker_id) {
          const worker = userById.get(t.assigned_worker_id);
          if (worker) {
            const fullName = [worker.surname, worker.name, worker.lastname]
              .filter(Boolean)
              .join(" ")
              .toLowerCase();
            if (fullName.includes(q)) return true;
          }
        }
        if (t.brigade_id) {
          const brigade = brigadeById.get(t.brigade_id);
          if (brigade && brigade.name.toLowerCase().includes(q)) return true;
        }
        return false;
      });
    }

    return tickets;
  }, [
    tickets,
    selectedBrigade,
    selectedWorker,
    searchTarget,
    searchQuery,
    users,
    userById,
    brigadeById,
  ]);

  // Задачи выбранного воркера для расчета его маршрута
  const workerTasks = useMemo(() => {
    if (!selectedWorker) return [];
    return tickets.filter((t) => t.assigned_worker_id === selectedWorker.id);
  }, [tickets, selectedWorker]);

  const { workerRoute } = useWorkerTasksRoute(
    selectedWorker,
    workerTasks,
    locationById,
    officesFullInfo,
  );

  const displayedWorkers = useMemo(() => {
    if (selectedWorker) {
      return workersFullInfo.filter((w) => w.id === selectedWorker.id);
    }
    if (selectedBrigade) {
      const brigadeWorkerIds = new Set(selectedBrigade.worker_ids || []);
      return workersFullInfo.filter(
        (w) => w.worker_profile?.brigade_id === selectedBrigade.id || brigadeWorkerIds.has(w.id),
      );
    }
    return workersFullInfo;
  }, [workersFullInfo, selectedBrigade, selectedWorker]);

  // Выбранный объект с проверкой его присутствия среди отображаемых тасок
  const effectiveSelectedObject = useMemo(() => {
    if (selectedObject?.type === "ticket") {
      const stillExists = displayedTickets.some((t) => t.id === selectedObject.id);
      return stillExists ? selectedObject : null;
    }
    return selectedObject;
  }, [displayedTickets, selectedObject]);

  // Плавное центрирование карты на тасках выбранной бригады или воркера
  useEffect(() => {
    if (!selectedBrigade && !selectedWorker) return;
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;

    const coords = displayedTickets
      .filter((t) => t.location?.longitude != null && t.location?.latitude != null)
      .map((t) => [t.location.longitude, t.location.latitude]);

    if (coords.length === 1) {
      map.flyTo({
        center: coords[0],
        zoom: 14,
        duration: 650,
      });
    } else if (coords.length > 1) {
      const bounds = coords.reduce(
        (result, point) => [
          [Math.min(result[0][0], point[0]), Math.min(result[0][1], point[1])],
          [Math.max(result[1][0], point[0]), Math.max(result[1][1], point[1])],
        ],
        [[Infinity, Infinity], [-Infinity, -Infinity]],
      );
      map.fitBounds(bounds, {
        padding: { top: 90, right: 380, bottom: 120, left: 90 },
        maxZoom: 14,
        duration: 650,
      });
    }
  }, [selectedBrigade, selectedWorker, displayedTickets, mapRef]);

  const filteredTickets = displayedTickets.filter((ticket) => {
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
      ? displayedWorkers.map((worker) => [worker.location.longitude, worker.location.latitude])
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
            <Search
              searchQuery={searchQuery}
              onSearchChange={handleSearchChange}
              onSelectResult={handleSelectResult}
              onClear={handleClearSearch}
            />
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
              <Menu
                selectedBrigade={selectedBrigade}
                onSelectBrigade={(brigade) => {
                  setSelectedBrigade(brigade);
                  setSelectedWorker(null);
                  if (!brigade) {
                    setSearchQuery("");
                    setSearchTarget(null);
                  } else {
                    setSearchQuery(`Бригада: ${brigade.name}`);
                    setSearchTarget({
                      type: "brigade",
                      id: brigade.id,
                      title: `Бригада: ${brigade.name}`,
                      raw: brigade,
                    });
                  }
                }}
                selectedWorker={selectedWorker}
                onSelectWorker={(worker) => {
                  setSelectedWorker(worker);
                  if (!worker) {
                    if (selectedBrigade) {
                      setSearchQuery(`Бригада: ${selectedBrigade.name}`);
                      setSearchTarget({
                        type: "brigade",
                        id: selectedBrigade.id,
                        title: `Бригада: ${selectedBrigade.name}`,
                        raw: selectedBrigade,
                      });
                    } else {
                      setSearchQuery("");
                      setSearchTarget(null);
                    }
                  } else {
                    const fullName = [worker.surname, worker.name, worker.lastname]
                      .filter(Boolean)
                      .join(" ");
                    setSearchQuery(`Сотрудник: ${fullName}`);
                    setSearchTarget({
                      type: "user",
                      id: worker.id,
                      title: `Сотрудник: ${fullName}`,
                      raw: worker,
                    });
                  }
                }}
              />
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
        tickets={displayedTickets}
        offices={officesFullInfo}
        workers={displayedWorkers}
        routes={routes}
        workerRoute={workerRoute}
        locationById={locationById}
        selectedObject={effectiveSelectedObject}
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
