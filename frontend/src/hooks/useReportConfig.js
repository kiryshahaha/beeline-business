import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useServiceAreas } from "./useServiceAreas";
import { useBrigades } from "./useBrigades";
import { useExportTickets } from "./useExportTickets";
import { apiFetch } from "@/lib/apiFetch";

export const REPORT_STATUS_OPTIONS = [
  { value: "all_except_wont_fix", label: "Все, кроме отменённых" },
  { value: "all", label: "Все статусы" },
  { value: "planned", label: "Запланировано" },
  { value: "in_progress", label: "В работе" },
  { value: "completed", label: "Выполнено" },
  { value: "wont_fix", label: "Отменено" },
];

export const CITIES_OPTIONS = [
  { value: "", label: "Все города" },
  { value: 1, label: "Москва" },
  { value: 2, label: "Санкт-Петербург" },
];

export const PERIOD_OPTIONS = [
  { value: "all", label: "За всё время" },
  { value: "today", label: "Сегодня" },
  { value: "week", label: "Текущая неделя" },
  { value: "month", label: "Текущий месяц" },
  { value: "dataset", label: "20–26 сентября 2026" },
];

function getPeriodDates(periodKey) {
  const now = new Date();
  const mskTodayStr = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Moscow" }).format(now);

  if (periodKey === "today") {
    return { date_from: mskTodayStr, date_to: mskTodayStr };
  }
  if (periodKey === "week") {
    const d = new Date(mskTodayStr + "T12:00:00Z");
    const day = d.getUTCDay();
    const diffToMonday = day === 0 ? -6 : 1 - day;
    const monday = new Date(d);
    monday.setUTCDate(d.getUTCDate() + diffToMonday);
    const sunday = new Date(monday);
    sunday.setUTCDate(monday.getUTCDate() + 6);
    return {
      date_from: monday.toISOString().slice(0, 10),
      date_to: sunday.toISOString().slice(0, 10),
    };
  }
  if (periodKey === "month") {
    const [year, month] = mskTodayStr.split("-");
    const firstDay = `${year}-${month}-01`;
    const lastDate = new Date(Number(year), Number(month), 0).getDate();
    const lastDay = `${year}-${month}-${String(lastDate).padStart(2, "0")}`;
    return { date_from: firstDay, date_to: lastDay };
  }
  if (periodKey === "dataset" || periodKey === "20–26 сентября 2026") {
    return { date_from: "2026-09-20", date_to: "2026-09-26" };
  }
  return { date_from: undefined, date_to: undefined };
}

export function useReportConfig() {
  const [selectedCityId, setSelectedCityId] = useState("");
  const [selectedAreaId, setSelectedAreaId] = useState("");
  const [selectedBrigadeId, setSelectedBrigadeId] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("all_except_wont_fix");
  const [selectedPeriod, setSelectedPeriod] = useState("all");

  const { serviceAreas = [] } = useServiceAreas();
  const { brigades = [] } = useBrigades();
  const { exportTickets, isExporting, exportError } = useExportTickets();

  const { date_from, date_to } = useMemo(() => getPeriodDates(selectedPeriod), [selectedPeriod]);
  const excludeCancelled = selectedStatus === "all_except_wont_fix";
  const effectiveStatus =
    selectedStatus === "all_except_wont_fix" || selectedStatus === "all" ? undefined : selectedStatus;
  const effectiveAreaId = selectedAreaId ? Number(selectedAreaId) : undefined;
  const effectiveBrigadeId = selectedBrigadeId ? Number(selectedBrigadeId) : undefined;
  const effectiveCityId = selectedCityId ? Number(selectedCityId) : undefined;

  // Динамический подсчет реального количества записей на бэкенде
  const { data: countData, isLoading: isCountLoading } = useQuery({
    queryKey: [
      "reportsTicketsCount",
      date_from,
      date_to,
      excludeCancelled,
      effectiveStatus,
      effectiveCityId,
      effectiveAreaId,
      effectiveBrigadeId,
    ],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (date_from) params.append("date_from", date_from);
      if (date_to) params.append("date_to", date_to);
      if (excludeCancelled) params.append("exclude_cancelled", "true");
      if (effectiveStatus) params.append("status", effectiveStatus);
      if (effectiveCityId) params.append("city_id", String(effectiveCityId));
      if (effectiveAreaId) params.append("service_area_id", String(effectiveAreaId));
      if (effectiveBrigadeId) params.append("brigade_id", String(effectiveBrigadeId));

      const res = await apiFetch(`/reports/tickets/count?${params}`);
      if (!res.ok) {
        return { count: 0 };
      }
      return await res.json();
    },
    staleTime: 15000,
  });

  const recordsCount = countData?.count ?? 0;

  const cityName =
    CITIES_OPTIONS.find((c) => String(c.value) === String(selectedCityId))?.label || "Все города";

  const areaName =
    selectedAreaId && serviceAreas.length > 0
      ? serviceAreas.find((a) => String(a.id) === String(selectedAreaId))?.name || "Все районы"
      : "Все районы";

  const brigadeName =
    selectedBrigadeId && brigades.length > 0
      ? brigades.find((b) => String(b.id) === String(selectedBrigadeId))?.name || "Все бригады"
      : "Все бригады";

  const periodLabel =
    PERIOD_OPTIONS.find((p) => p.value === selectedPeriod)?.label || selectedPeriod;

  const handleDownloadCSV = () => {
    return exportTickets({
      format: "csv",
      status: effectiveStatus,
      exclude_cancelled: excludeCancelled,
      date_from,
      date_to,
      city_id: effectiveCityId,
      service_area_id: effectiveAreaId,
      brigade_id: effectiveBrigadeId,
      profile: "human",
    });
  };

  const handleDownloadXLSX = () => {
    return exportTickets({
      format: "xlsx",
      status: effectiveStatus,
      exclude_cancelled: excludeCancelled,
      date_from,
      date_to,
      city_id: effectiveCityId,
      service_area_id: effectiveAreaId,
      brigade_id: effectiveBrigadeId,
      profile: "human",
    });
  };

  return {
    selectedCityId,
    setSelectedCityId,
    selectedAreaId,
    setSelectedAreaId,
    selectedBrigadeId,
    setSelectedBrigadeId,
    selectedStatus,
    setSelectedStatus,
    selectedPeriod,
    setSelectedPeriod,
    serviceAreas,
    brigades,
    recordsCount,
    isCountLoading,
    cityName,
    areaName,
    brigadeName,
    periodLabel,
    handleDownloadCSV,
    handleDownloadXLSX,
    isExporting,
    exportError,
  };
}
