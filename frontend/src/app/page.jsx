"use client";

import MapComponent from "@/components/MapComponent";
import Search from "@/components/Search/Search";
import DistrictFilter from "@/components/DistrictFilter/DistrictFilter";
import TicketsStatuses from "@/components/TicketsStatuses/TicketsStatuses";
import Notifications from "@/components/Notifications/Notifications";
import Layers from "@/components/Layers/Layers";
import Menu from "@/components/Menu/Menu";
import CreateTicketModal from "@/components/Modals/CreateTicketModal";
import StarrySky from "@/components/StarrySky/StarrySky";
import { useTickets } from "@/hooks/useTickets";
import { useEffect, useMemo, useRef, useState } from "react";
import { useOffices } from "@/hooks/useOffices";
import { useLocations } from "@/hooks/useLocations";
import { useUsers } from "@/hooks/useUsers";
import { useRoutes } from "@/hooks/useRoutes";
import { useWorkerTasksRoute } from "@/hooks/useWorkerTasksRoute";
import { useBrigades } from "@/hooks/useBrigades";
import { fetchRealDistrictBoundary, isPointInPolygon } from "@/utils/districtGeometry";
import { isTicketUrgent } from "@/utils/ticketUtils";
import { apiFetch } from "@/lib/apiFetch";
import { useAuth } from "@/providers/AuthProvider";

export const MOSCOW_ADMIN_OKRUGS = [
  { name: "Центральный административный округ", shortName: "ЦАО", city: "Москва", aliases: ["цао", "центр", "центральный ао"] },
  { name: "Северный административный округ", shortName: "САО", city: "Москва", aliases: ["сао", "север"] },
  { name: "Северо-Восточный административный округ", shortName: "СВАО", city: "Москва", aliases: ["свао", "северо-восток"] },
  { name: "Восточный административный округ", shortName: "ВАО", city: "Москва", aliases: ["вао", "восток", "офис восток"] },
  { name: "Юго-Восточный административный округ", shortName: "ЮВАО", city: "Москва", aliases: ["ювао", "юго-восток", "офис юго-восток"] },
  { name: "Южный административный округ", shortName: "ЮАО", city: "Москва", aliases: ["юао", "юг", "югоцентр", "офис югоцентр"] },
  { name: "Юго-Западный административный округ", shortName: "ЮЗАО", city: "Москва", aliases: ["юзао", "юго-запад"] },
  { name: "Западный административный округ", shortName: "ЗАО", city: "Москва", aliases: ["зао", "запад"] },
  { name: "Северо-Западный административный округ", shortName: "СЗАО", city: "Москва", aliases: ["сзао", "северо-запад"] },
  { name: "Зеленоградский административный округ", shortName: "ЗелАО", city: "Москва", aliases: ["зелао", "зеленоград"] },
  { name: "Новомосковский административный округ", shortName: "НАО", city: "Москва", aliases: ["нао", "новомосковский", "новая москва"] },
  { name: "Троицкий административный округ", shortName: "ТАО", city: "Москва", aliases: ["тао", "троицкий", "троицк"] },
];

export default function Home() {
  const { token } = useAuth();
  const mapRef = useRef(null);
  const [selectedBrigade, setSelectedBrigade] = useState(null);
  const [selectedWorker, setSelectedWorker] = useState(null);
  const { tickets, ticketsData } = useTickets({
    limit: 100,
    offset: 0,
    ...(selectedBrigade ? { brigade_id: selectedBrigade.id } : {}),
  });
  const [createdTickets, setCreatedTickets] = useState(() => {
    if (typeof window === "undefined") return [];
    try {
      const cached = JSON.parse(localStorage.getItem("beeline_created_tickets_cache") || "[]");
      if (Array.isArray(cached) && cached.length > 0) return cached;
    } catch {}
    return [
      {
        id: 3010,
        title: "тест123",
        description: null,
        work_type_id: 9,
        work_type: "Работы на подключение и дозаказы",
        category: "repair",
        priority: 3,
        status: "planned",
        location_id: 1011,
        location: {
          id: 1011,
          city: "Москва",
          district: "Тверской",
          street: "Тверская",
          building_number: "1",
          latitude: 55.7558,
          longitude: 37.6173,
          address: "Москва, Тверской, Тверская, д. 1",
        },
      },
    ];
  });

  // Восстановление созданных заявок пользователя
  useEffect(() => {
    if (!token) return;
    try {
      const savedIds = JSON.parse(localStorage.getItem("beeline_created_ticket_ids") || "[]");
      const allKnownIds = [...new Set([3010, 3009, ...(Array.isArray(savedIds) ? savedIds : [])])];
      if (allKnownIds.length > 0) {
        Promise.all(
          allKnownIds.slice(0, 25).map((id) =>
            apiFetch(`/tickets/${id}`)
              .then((res) => (res.ok ? res.json() : null))
              .catch(() => null)
          )
        ).then((fetched) => {
          const valid = fetched.filter(Boolean);
          if (valid.length > 0) {
            setCreatedTickets((prev) => {
              const map = new Map(prev.map((t) => [t.id, t]));
              valid.forEach((t) => map.set(t.id, t));
              const updated = Array.from(map.values());
              try {
                localStorage.setItem("beeline_created_tickets_cache", JSON.stringify(updated.slice(0, 50)));
              } catch {}
              return updated;
            });
          }
        });
      }
    } catch (e) {
      console.warn("Failed to restore created tickets:", e);
    }
  }, [token]);

  const allTickets = useMemo(() => {
    if (!createdTickets.length) return tickets;
    const existingIds = new Set(tickets.map((t) => t.id));
    const newOnes = createdTickets.filter((t) => !existingIds.has(t.id));
    return [...newOnes, ...tickets];
  }, [tickets, createdTickets]);
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
  const [selectedDistrict, setSelectedDistrict] = useState(null);
  const [focusedOffice, setFocusedOffice] = useState(null);
  const [pinnedTicketId, setPinnedTicketId] = useState(null);
  const [showDistrictBoundary, setShowDistrictBoundary] = useState(true);
  const [filterTicketsByDistrict, setFilterTicketsByDistrict] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchTarget, setSearchTarget] = useState(null);
  const [ticketStatusFilter, setTicketStatusFilter] = useState("all");
  const [districtBoundaryData, setDistrictBoundaryData] = useState(null);
  const [isLoadingBoundary, setIsLoadingBoundary] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createModalCoords, setCreateModalCoords] = useState(null);
  const [isPinPickMode, setIsPinPickMode] = useState(false);

  // Восстановление настроек карты из localStorage
  useEffect(() => {
    try {
      const savedBoundaries = localStorage.getItem("beeline_show_boundaries");
      if (savedBoundaries !== null) {
        queueMicrotask(() => {
          setShowDistrictBoundary(savedBoundaries === "true");
        });
      }
    } catch {}
  }, []);

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
        return location
          ? {
              ...location,
              office_id: office.id,
              office_name: office.name,
              district: location.district || office.district,
              service_area_id: location.service_area_id || office.service_area_id,
            }
          : { ...office, office_id: office.id, office_name: office.name };
      })
      .filter(Boolean);
  }, [offices, locationById]);

  // Справочник всех районов в системе (из офисов и заявок)
  const districtsList = useMemo(() => {
    const districtMap = new Map();

    // Из офисов
    officesFullInfo.forEach((office) => {
      const name = office.district;
      if (!name) return;
      if (!districtMap.has(name)) {
        districtMap.set(name, {
          name,
          service_area_id: office.service_area_id,
          office,
          ticketsCount: 0,
        });
      } else {
        const existing = districtMap.get(name);
        if (!existing.office) existing.office = office;
        if (office.service_area_id && !existing.service_area_id) {
          existing.service_area_id = office.service_area_id;
        }
      }
    });

    // Из заявок
    allTickets.forEach((t) => {
      const loc = t.location || locationById.get(t.location_id);
      const name = t.district || loc?.district;
      if (!name) return;
      const saId = t.service_area_id || loc?.service_area_id;

      if (!districtMap.has(name)) {
        districtMap.set(name, {
          name,
          service_area_id: saId,
          office: null,
          ticketsCount: 1,
        });
      } else {
        const existing = districtMap.get(name);
        existing.ticketsCount += 1;
        if (saId && !existing.service_area_id) {
          existing.service_area_id = saId;
        }
      }
    });

    // Административные округа Москвы
    MOSCOW_ADMIN_OKRUGS.forEach((okrug) => {
      const office = officesFullInfo.find((o) => {
        const d = (o.district || "").toLowerCase();
        const n = (o.office_name || "").toLowerCase();
        return (
          d === okrug.name.toLowerCase() ||
          okrug.aliases.some((a) => d === a || n.includes(a))
        );
      });

      if (!districtMap.has(okrug.name)) {
        districtMap.set(okrug.name, {
          name: okrug.name,
          shortName: okrug.shortName,
          city: "Москва",
          isOkrug: true,
          aliases: okrug.aliases,
          service_area_id: office?.service_area_id,
          office: office || null,
          ticketsCount: 0,
        });
      } else {
        const existing = districtMap.get(okrug.name);
        existing.shortName = okrug.shortName;
        existing.city = "Москва";
        existing.isOkrug = true;
        existing.aliases = okrug.aliases;
        if (office && !existing.office) existing.office = office;
      }
    });

    return Array.from(districtMap.values()).sort((a, b) => a.name.localeCompare(b.name, "ru"));
  }, [officesFullInfo, allTickets, locationById]);

  // Выбранный офис (если тип объекта — office или сохранен фокус)
  const selectedOffice = useMemo(() => {
    if (selectedObject?.type === "office") {
      return officesFullInfo.find(
        (o) => o.office_id === selectedObject.id || o.id === selectedObject.id
      ) || null;
    }
    if (focusedOffice) {
      return officesFullInfo.find(
        (o) => o.office_id === focusedOffice.office_id || o.id === focusedOffice.id
      ) || focusedOffice;
    }
    return null;
  }, [officesFullInfo, selectedObject, focusedOffice]);

  // Активный район: выбран через поиск/фильтр ИЛИ выведен из клика по офису
  const activeDistrict = useMemo(() => {
    if (selectedDistrict) return selectedDistrict;
    if (focusedOffice?.district) return focusedOffice.district;
    if (selectedOffice?.district) return selectedOffice.district;
    return null;
  }, [selectedDistrict, focusedOffice, selectedOffice]);

  const activeDistrictObj = useMemo(() => {
    if (!activeDistrict) return null;
    return districtsList.find((d) => d.name.toLowerCase() === activeDistrict.toLowerCase()) || null;
  }, [activeDistrict, districtsList]);

  const brigadeById = useMemo(() => new Map(brigades.map((b) => [b.id, b])), [brigades]);
  const userById = useMemo(() => new Map(users.map((u) => [u.id, u])), [users]);

  const workersFullInfo = useMemo(() => {
    return users
      .filter((user) => !user.archived_at)
      .map((user) => {
        const brigade = user.brigade_id ? brigadeById.get(user.brigade_id) : null;
        const office = brigade?.office_id
          ? officesFullInfo.find((o) => o.office_id === brigade.office_id || o.id === brigade.office_id)
          : null;
        const startLocId = user.worker_profile?.start_location_id || office?.location_id;
        const loc = startLocId ? locationById.get(startLocId) : null;
        const effectiveServiceAreaId =
          user.worker_profile?.service_area_id ??
          user.service_area_id ??
          brigade?.service_area_id ??
          office?.service_area_id;

        return {
          ...user,
          location: loc || (office ? { latitude: office.latitude, longitude: office.longitude, address: office.address, district: office.district } : null),
          brigade_name: user.brigade_name || brigade?.name || (brigade ? `Бригада #${brigade.id}` : null),
          service_area_id: effectiveServiceAreaId,
        };
      });
  }, [users, locationById, brigadeById, officesFullInfo]);

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
    setVisibleLayers((current) => ({
      ...current,
      [layer]: true,
      routes: type === "route" ? true : current.routes,
    }));

    if (type === "ticket") {
      setPinnedTicketId(id);
    }

    // При клике на офис автоматически активируем его район и фиксируем фокус офиса
    if (type === "office") {
      const office = officesFullInfo.find((o) => o.office_id === id || o.id === id);
      if (office) {
        setFocusedOffice(office);
        if (office.district) {
          setSelectedDistrict(office.district);
        }
      }
    }
  };

  // Загрузка реальных гео-границ района через Geoapify / OSM GeoJSON
  useEffect(() => {
    let isCancelled = false;

    // Определяем параметры для запроса границы
    const currentOffice = focusedOffice || selectedOffice;
    const lat = currentOffice?.latitude;
    const lon = currentOffice?.longitude;
    const district = activeDistrict || currentOffice?.district;
    const isOkrug =
      activeDistrictObj?.isOkrug ||
      (district && district.toLowerCase().includes("округ"));
    const city =
      currentOffice?.city ||
      (isOkrug ? "Москва" : (activeDistrict ? "Санкт-Петербург" : undefined));

    if (!district && (lat == null || lon == null)) {
      Promise.resolve().then(() => {
        if (!isCancelled) {
          setDistrictBoundaryData(null);
          setIsLoadingBoundary(false);
        }
      });
      return () => {
        isCancelled = true;
      };
    }

    Promise.resolve().then(() => {
      if (!isCancelled) {
        setIsLoadingBoundary(true);
      }
    });

    fetchRealDistrictBoundary({
      district: district || undefined,
      city,
      lat: lat != null && Number.isFinite(Number(lat)) ? Number(lat) : undefined,
      lon: lon != null && Number.isFinite(Number(lon)) ? Number(lon) : undefined,
    })
      .then((data) => {
        if (!isCancelled) {
          setDistrictBoundaryData(data);
          setIsLoadingBoundary(false);
          // Если название района определилось через Geoapify при клике на офис
          if (data?.districtName && selectedDistrict !== data.districtName && currentOffice) {
            setSelectedDistrict(data.districtName);
          }
        }
      })
      .catch((err) => {
        console.error("Failed to load district boundary:", err);
        if (!isCancelled) {
          setDistrictBoundaryData(null);
          setIsLoadingBoundary(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [activeDistrict, activeDistrictObj?.isOkrug, focusedOffice, selectedOffice, selectedDistrict]);

  const deselectObject = () => {
    setSelectedObject(null);
  };

  const resetDistrictFocus = () => {
    setSelectedObject(null);
    setFocusedOffice(null);
    setSelectedDistrict(null);
    setPinnedTicketId(null);
    setDistrictBoundaryData(null);
    if (searchTarget?.type === "district") {
      setSearchTarget(null);
      setSearchQuery("");
    }
  };

  const handleSelectResult = (result) => {
    if (result.type === "district") {
      const districtName = result.raw.name;
      setSearchTarget({ type: "district", id: districtName, title: result.title, raw: result.raw });
      setSearchQuery(result.title);
      setSelectedDistrict(districtName);
      setSelectedBrigade(null);
      setSelectedWorker(null);

      // Если в этом районе есть офис, выделяем его
      if (result.raw.office) {
        setFocusedOffice(result.raw.office);
        selectObject("office", result.raw.office.office_id);
      } else {
        setFocusedOffice(null);
        setSelectedObject(null);
      }
      return true;
    }

    if (result.type === "ticket") {
      if (result.raw.location?.longitude == null || result.raw.location?.latitude == null) return false;
      setSearchTarget({ type: "ticket", id: result.raw.id, title: result.title, raw: result.raw });
      setSearchQuery(result.title);
      setSelectedBrigade(null);
      setSelectedWorker(null);
      setTicketStatusFilter("all");
      selectObject("ticket", result.raw.id);
      return true;
    }

    if (result.type === "user") {
      resetDistrictFocus();
      setSearchTarget({ type: "user", id: result.raw.id, title: result.title, raw: result.raw });
      setSearchQuery(result.title);
      setSelectedWorker(result.raw);
      setSelectedBrigade(null);
      setSelectedObject(null);
      return true;
    }

    if (result.type === "brigade") {
      resetDistrictFocus();
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
      resetDistrictFocus();
    } else if (searchTarget && newQuery !== searchTarget.title) {
      setSearchTarget(null);
      setSelectedBrigade(null);
      setSelectedWorker(null);
      if (searchTarget.type === "district") {
        resetDistrictFocus();
      }
    }
  };

  const handleClearSearch = () => {
    setSearchQuery("");
    setSearchTarget(null);
    setSelectedBrigade(null);
    setSelectedWorker(null);
    resetDistrictFocus();
  };

  const toggleLayer = (layer) => {
    setVisibleLayers((current) => ({ ...current, [layer]: !current[layer] }));
  };

  // 3.0. Фильтрация тасок по активному району (при клике на офис, выборе из поиска или фильтра)
  // Используется РЕАЛЬНОЕ вхождение точки в GeoJSON-полигон Geoapify (isPointInPolygon)
  // и проверка по названию района/service_area_id.
  const districtFilteredTickets = useMemo(() => {
    if (!filterTicketsByDistrict) return allTickets;
    const currentOffice = focusedOffice || selectedOffice;
    if (!activeDistrict && !currentOffice) return allTickets;

    const lowerDistrict = (activeDistrict || currentOffice?.district || "").trim().toLowerCase();
    const saId = activeDistrictObj?.service_area_id || currentOffice?.service_area_id;
    const geom = districtBoundaryData?.geometry;

    return allTickets.filter((t) => {
      // Всегда сохраняем выбранную, зафиксированную или только что созданную заявку!
      if (t.id === pinnedTicketId || t.id === selectedObject?.id) return true;
      if (createdTickets.some((ct) => ct.id === t.id)) return true;

      const loc = t.location || locationById.get(t.location_id);
      if (!loc) return false;

      // 1. Пространственная проверка: находится ли точка внутри официального GeoJSON-полигона
      if (geom && Number.isFinite(loc.longitude) && Number.isFinite(loc.latitude)) {
        if (isPointInPolygon([loc.longitude, loc.latitude], geom)) {
          return true;
        }
      }

      // 2. Проверка по совпадению названия района
      const tDistrict = (t.district || loc?.district || "").trim().toLowerCase();
      if (lowerDistrict && tDistrict && tDistrict === lowerDistrict) return true;
      if (
        districtBoundaryData?.districtName &&
        tDistrict &&
        tDistrict === districtBoundaryData.districtName.trim().toLowerCase()
      ) {
        return true;
      }

      // 3. Проверка по service_area_id
      if (saId != null) {
        const tSaId = t.service_area_id ?? loc?.service_area_id;
        if (tSaId != null && Number(tSaId) === Number(saId)) return true;
      }

      return false;
    });
  }, [
    allTickets,
    filterTicketsByDistrict,
    activeDistrict,
    activeDistrictObj,
    focusedOffice,
    selectedOffice,
    districtBoundaryData,
    locationById,
    pinnedTicketId,
    selectedObject,
    createdTickets,
  ]);

  // 3.1. Реальные GeoJSON границы и bounds района
  const districtBoundary = districtBoundaryData?.featureCollection || null;
  const districtBounds = districtBoundaryData?.bounds || null;

  // 3.2. Фильтрация тасок по выбранному воркеру, бригаде или поисковому запросу
  const displayedTickets = useMemo(() => {
    // При выборе конкретной бригады или сотрудника отображаем их задачи независимо от выбранного ранее района
    const baseTickets = (selectedBrigade || selectedWorker) ? allTickets : districtFilteredTickets;

    // Если выбран инженер (через меню или поиск) -> показываем ТОЛЬКО его таски
    if (selectedWorker) {
      return baseTickets.filter((t) => t.assigned_worker_id === selectedWorker.id);
    }

    // Если выбрана бригада (через меню или поиск) -> показываем ТОЛЬКО её таски
    if (selectedBrigade) {
      const brigadeWorkerIds = new Set(selectedBrigade.worker_ids || []);
      users.forEach((u) => {
        if (u.brigade_id === selectedBrigade.id || u.worker_profile?.brigade_id === selectedBrigade.id) {
          brigadeWorkerIds.add(u.id);
        }
      });

      return baseTickets.filter((t) => {
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
    let result = baseTickets;
    if (searchTarget?.type === "ticket") {
      result = baseTickets;
    } else if (searchTarget?.type === "district") {
      result = baseTickets;
    } else {
      // Фильтрация вывода тасок под условия ввода в поиске
      const q = searchQuery.trim().toLowerCase();
      if (q && !q.startsWith("район:")) {
        const qClean = q.replace(/^#/, "");
        result = baseTickets.filter((t) => {
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
    }

    // Гарантируем присутствие выбранной пользователем заявки в списке (чтобы отображался ее маркер)
    if (selectedObject?.type === "ticket") {
      const selectedTicket = allTickets.find((t) => t.id === selectedObject.id) || selectedObject.ticket;
      if (selectedTicket && !result.some((t) => t.id === selectedObject.id)) {
        result = [selectedTicket, ...result];
      }
    }

    // Гарантируем присутствие недавно созданных заявок, если не выбрана отдельная бригада
    if (createdTickets.length > 0 && !selectedBrigade && !selectedWorker) {
      const existingIds = new Set(result.map((t) => t.id));
      const missingCreated = createdTickets.filter((t) => !existingIds.has(t.id));
      if (missingCreated.length > 0) {
        result = [...missingCreated, ...result];
      }
    }

    return result;
  }, [
    allTickets,
    districtFilteredTickets,
    selectedBrigade,
    selectedWorker,
    searchTarget,
    searchQuery,
    users,
    userById,
    brigadeById,
    selectedObject,
    createdTickets,
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
        (w) =>
          w.brigade_id === selectedBrigade.id ||
          w.worker_profile?.brigade_id === selectedBrigade.id ||
          brigadeWorkerIds.has(w.id),
      );
    }
    return workersFullInfo;
  }, [workersFullInfo, selectedBrigade, selectedWorker]);

  // Выбранный объект с проверкой его присутствия среди отображаемых тасок
  const effectiveSelectedObject = useMemo(() => {
    if (selectedObject?.type === "ticket") {
      const stillExists = displayedTickets.some((t) => t.id === selectedObject.id);
      if (stillExists) return selectedObject;
      if (selectedObject.ticket) return selectedObject;
      return null;
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

  const filteredTickets = useMemo(() => {
    return displayedTickets.filter((ticket) => {
      if (ticketStatusFilter === "urgent") return isTicketUrgent(ticket);
      if (ticketStatusFilter === "in_progress") return ticket.status === "in_progress";
      if (ticketStatusFilter === "completed") return ticket.status === "completed";
      return true;
    });
  }, [displayedTickets, ticketStatusFilter]);
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

  const activeRouteTicket = useMemo(() => {
    const id = selectedObject?.type === "ticket" ? selectedObject.id : pinnedTicketId;
    if (!id) return null;
    return tickets.find((t) => t.id === id) || null;
  }, [selectedObject, pinnedTicketId, tickets]);

  const handleFitDistrict = () => {
    const map = mapRef?.current?.getMap?.() || mapRef?.current;
    if (!map) return;
    if (districtBounds) {
      map.fitBounds(districtBounds, {
        padding: { top: 90, right: 380, bottom: 90, left: 100 },
        duration: 750,
      });
    } else {
      const currentOffice = focusedOffice || selectedOffice;
      if (currentOffice?.longitude != null && currentOffice?.latitude != null) {
        map.flyTo({
          center: [currentOffice.longitude, currentOffice.latitude],
          zoom: 13,
          duration: 750,
        });
      }
    }
  };

  return (
    <main
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100dvh",
        overflow: "hidden",
        overscrollBehavior: "none",
        backgroundColor: "#0c0d12",
      }}
    >
      {/* Космическое звёздное небо на фоне карты */}
      <StarrySky />
      {/* Баннер режима выбора точки на карте */}
      {isPinPickMode && (
        <div
          style={{
            position: "absolute",
            top: 24,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 3500,
            background: "#FFC800",
            color: "#1C1C1E",
            padding: "9px 20px",
            borderRadius: "30px",
            boxShadow: "0 10px 32px rgba(0, 0, 0, 0.55)",
            fontWeight: 700,
            fontSize: "13px",
            display: "flex",
            alignItems: "center",
            gap: "10px",
            cursor: "pointer",
            userSelect: "none",
          }}
          onClick={() => setIsPinPickMode(false)}
          title="Нажмите, чтобы отменить выбор точки на карте"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="22" y1="12" x2="18" y2="12"></line>
            <line x1="6" y1="12" x2="2" y2="12"></line>
            <line x1="12" y1="6" x2="12" y2="2"></line>
            <line x1="12" y1="22" x2="12" y2="18"></line>
          </svg>
          <span>Кликните на карте, чтобы поставить заявку</span>
          <span style={{ opacity: 0.65, fontSize: "11px", textDecoration: "underline" }}>[Отмена]</span>
        </div>
      )}

      <div
        style={{
          position: "absolute",
          inset: 22,
          pointerEvents: "none",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          zIndex: 2000,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ pointerEvents: "auto", display: "flex", gap: "8px", alignItems: "flex-start" }}>
            <Search
              searchQuery={searchQuery}
              onSearchChange={handleSearchChange}
              onSelectResult={handleSelectResult}
              onClear={handleClearSearch}
              districts={districtsList}
            />
            <DistrictFilter
              districts={districtsList}
              selectedDistrict={activeDistrict}
              onSelectDistrict={(districtName) => {
                if (!districtName) {
                  resetDistrictFocus();
                } else {
                  setSelectedDistrict(districtName);
                  const targetDist = districtsList.find(
                    (d) => d.name.toLowerCase() === districtName.toLowerCase()
                  );
                  if (targetDist?.office) {
                    setFocusedOffice(targetDist.office);
                    selectObject("office", targetDist.office.office_id);
                  } else {
                    setFocusedOffice(null);
                    setSelectedObject(null);
                  }
                }
              }}
            />
            <button
              type="button"
              id="create-ticket-top-btn"
              onClick={() => {
                setCreateModalCoords(null);
                setIsCreateModalOpen(true);
              }}
              style={{
                height: "32px",
                padding: "0 13px",
                borderRadius: "12px",
                background: "var(--beeline)",
                border: "1px solid rgba(0, 0, 0, 0.12)",
                color: "#111111",
                fontSize: "12.5px",
                fontWeight: 700,
                display: "inline-flex",
                alignItems: "center",
                gap: "5px",
                cursor: "pointer",
                boxShadow: "var(--shadow-sm)",
                transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
                whiteSpace: "nowrap",
                userSelect: "none",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = "var(--beeline-hover)";
                e.currentTarget.style.transform = "translateY(-1px)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--beeline)";
                e.currentTarget.style.transform = "none";
              }}
              title="Создать новую заявку на обслуживание"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#111111" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              <span>Заявка</span>
            </button>
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
                activeDistrict={activeDistrict}
                focusedOffice={focusedOffice || selectedOffice}
                showDistrictBoundary={showDistrictBoundary}
                onToggleDistrictBoundary={() => setShowDistrictBoundary((prev) => !prev)}
                filterTicketsByDistrict={filterTicketsByDistrict}
                onToggleFilterTicketsByDistrict={() => setFilterTicketsByDistrict((prev) => !prev)}
                activeRouteTicket={activeRouteTicket}
                onClearRoute={() => setPinnedTicketId(null)}
                onFitDistrict={handleFitDistrict}
                onClearDistrict={resetDistrictFocus}
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
                    resetDistrictFocus();
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
              tickets={displayedTickets}
              selectedDistrict={activeDistrict}
              onClearDistrict={resetDistrictFocus}
              onSelectTicket={(ticket) => {
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
        allWorkers={workersFullInfo}
        routes={routes}
        workerRoute={workerRoute}
        locationById={locationById}
        selectedObject={effectiveSelectedObject}
        pinnedTicketId={pinnedTicketId}
        districtBoundary={districtBoundary}
        districtBounds={districtBounds}
        showDistrictBoundary={showDistrictBoundary}
        ticketStatusFilter={ticketStatusFilter}
        visibleLayers={visibleLayers}
        onSelectObject={selectObject}
        onClearSelection={deselectObject}
        onMapContextMenu={(coords) => {
          setCreateModalCoords(coords);
          setIsCreateModalOpen(true);
        }}
        isPinPickMode={isPinPickMode}
        onPinPick={(coords) => {
          setCreateModalCoords(coords);
          setIsPinPickMode(false);
          setIsCreateModalOpen(true);
        }}
        isDataReady={
          !ticketsData.isLoading
          && !officesData.isLoading
          && !usersData.isLoading
          && !routesData.isLoading
          && locationQueries.every((query) => !query.isLoading)
        }
      />

      <CreateTicketModal
        isOpen={isCreateModalOpen}
        initialCoordinates={createModalCoords}
        onStartPickOnMap={() => {
          setIsCreateModalOpen(false);
          setIsPinPickMode(true);
        }}
        onClose={() => {
          setIsCreateModalOpen(false);
          setCreateModalCoords(null);
        }}
        onTicketCreated={(newTicket) => {
          setCreatedTickets((prev) => [newTicket, ...prev.filter((t) => t.id !== newTicket.id)]);
          try {
            const savedCache = JSON.parse(localStorage.getItem("beeline_created_tickets_cache") || "[]");
            localStorage.setItem(
              "beeline_created_tickets_cache",
              JSON.stringify([newTicket, ...savedCache.filter((t) => t.id !== newTicket.id)].slice(0, 50))
            );
            const saved = JSON.parse(localStorage.getItem("beeline_created_ticket_ids") || "[]");
            if (!saved.includes(newTicket.id)) {
              localStorage.setItem(
                "beeline_created_ticket_ids",
                JSON.stringify([newTicket.id, ...saved].slice(0, 50))
              );
            }
          } catch {}

          const coords = [
            newTicket.location?.longitude ?? 37.6173,
            newTicket.location?.latitude ?? 55.7558,
          ];
          const map = mapRef.current?.getMap?.() || mapRef.current;
          if (coords[0] && coords[1] && map?.flyTo) {
            map.flyTo({
              center: coords,
              zoom: 15,
              duration: 800,
            });
          }
          if (newTicket?.id) {
            selectObject("ticket", newTicket.id, {
              ticket: newTicket,
              coordinates: coords,
            });
          }
        }}
      />
    </main>
  );
}
