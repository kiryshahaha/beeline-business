import { useState, useMemo } from "react";
import { useServiceAreas } from "./useServiceAreas";
import { useBrigades } from "./useBrigades";
import { useTickets } from "./useTickets";
import { useExportTickets } from "./useExportTickets";

export const REPORT_STATUS_OPTIONS = [
  { value: "all_except_wont_fix", label: "Все, кроме отменённых" },
  { value: "planned", label: "Запланировано" },
  { value: "in_progress", label: "В работе" },
  { value: "completed", label: "Выполнено" },
  { value: "wont_fix", label: "Отменено" },
];

export const CITIES_OPTIONS = [{ value: 1, label: "Москва" }];

export function useReportConfig() {
  const [selectedCityId, setSelectedCityId] = useState(1);
  const [selectedAreaId, setSelectedAreaId] = useState("");
  const [selectedBrigadeId, setSelectedBrigadeId] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("all_except_wont_fix");
  const [selectedPeriod, setSelectedPeriod] = useState("20–26 сентября 2026");

  const { serviceAreas, serviceAreasData } = useServiceAreas();
  const { brigades, brigadesData } = useBrigades();
  const { exportTickets, isExporting, exportError } = useExportTickets();

  // Параметры для фильтрации заявок
  const effectiveStatus =
    selectedStatus === "all_except_wont_fix" ? undefined : selectedStatus;
  const effectiveAreaId = selectedAreaId ? Number(selectedAreaId) : undefined;
  const effectiveBrigadeId = selectedBrigadeId ? Number(selectedBrigadeId) : undefined;
  const effectiveCityId = selectedCityId ? Number(selectedCityId) : undefined;

  // Запрос для получения подходящих заявок и их количества
  const { tickets, ticketsData } = useTickets({
    status: effectiveStatus,
    service_area_id: effectiveAreaId,
    brigade_id: effectiveBrigadeId,
    city_id: effectiveCityId,
    limit: 100,
    offset: 0,
  });

  // Человекочитаемые подписи выбранных фильтров
  const cityName =
    CITIES_OPTIONS.find((c) => c.value === Number(selectedCityId))?.label || "Все города";

  const areaName =
    selectedAreaId && serviceAreas.length > 0
      ? serviceAreas.find((a) => String(a.id) === String(selectedAreaId))?.name || "Выбранный район"
      : "Все районы";

  const brigadeName =
    selectedBrigadeId && brigades.length > 0
      ? brigades.find((b) => String(b.id) === String(selectedBrigadeId))?.name || "Выбранная бригада"
      : "Все бригады";

  const statusLabel =
    REPORT_STATUS_OPTIONS.find((s) => s.value === selectedStatus)?.label || "Все статусы";

  // Количество записей (из списка или дефолт)
  const recordsCount = tickets?.length ?? 0;

  // Сформированное краткое описание отчёта
  const reportDescription = useMemo(() => {
    const parts = [
      cityName,
      areaName,
      brigadeName,
      `${recordsCount} записей`,
      "часовой пояс UTC+3",
    ];
    return `${parts.join(" · ")}. Включены SLA, адрес, категория, исполнитель, сроки и история статусов.`;
  }, [cityName, areaName, brigadeName, recordsCount]);

  const handleDownloadCSV = () => {
    return exportTickets({
      format: "csv",
      status: effectiveStatus,
      city_id: effectiveCityId,
      service_area_id: effectiveAreaId,
      brigade_id: effectiveBrigadeId,
    });
  };

  const handleDownloadXLSX = () => {
    return exportTickets({
      format: "xlsx",
      status: effectiveStatus,
      city_id: effectiveCityId,
      service_area_id: effectiveAreaId,
      brigade_id: effectiveBrigadeId,
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
    isLoadingOptions: serviceAreasData.isLoading || brigadesData.isLoading,
    recordsCount,
    reportDescription,
    handleDownloadCSV,
    handleDownloadXLSX,
    isExporting,
    exportError,
    ticketsData,
  };
}
