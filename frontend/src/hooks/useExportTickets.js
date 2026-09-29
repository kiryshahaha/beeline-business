import { useState, useCallback } from "react";
import { apiFetch } from "@/lib/apiFetch";

/**
 * Извлечение имени файла из заголовка Content-Disposition
 */
function extractFilename(contentDisposition, defaultName) {
  if (!contentDisposition) return defaultName;
  const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
  return match && match[1] ? decodeURIComponent(match[1]) : defaultName;
}

export function useExportTickets() {
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState(null);

  const exportTickets = useCallback(
    async ({
      format = "xlsx",
      status,
      city_id,
      service_area_id,
      brigade_id,
      date_from,
      date_to,
      exclude_cancelled = false,
      profile = "human",
    } = {}) => {
      setIsExporting(true);
      setExportError(null);

      try {
        const urlParams = new URLSearchParams({ format, profile });
        
        if (status && status !== "all" && status !== "all_except_wont_fix") {
          urlParams.append("status", status);
        }
        if (exclude_cancelled) {
          urlParams.append("exclude_cancelled", "true");
        }
        if (date_from) urlParams.append("date_from", date_from);
        if (date_to) urlParams.append("date_to", date_to);
        if (city_id) urlParams.append("city_id", String(city_id));
        if (service_area_id) urlParams.append("service_area_id", String(service_area_id));
        if (brigade_id) urlParams.append("brigade_id", String(brigade_id));

        const res = await apiFetch(`/reports/tickets/export?${urlParams}`);

        if (!res.ok) {
          let errorMsg = `Ошибка скачивания отчёта (${res.status})`;
          try {
            const errData = await res.json();
            if (errData?.detail) {
              errorMsg = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
            }
          } catch {
            // Игнорируем ошибку парсинга тела
          }
          throw new Error(errorMsg);
        }

        const blob = await res.blob();
        const contentDisposition = res.headers.get("content-disposition");
        const filename = extractFilename(contentDisposition, `tickets_report.${format}`);

        // Инициируем скачивание файла в браузере
        const downloadUrl = window.URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(downloadUrl);

        return { success: true, filename };
      } catch (err) {
        setExportError(err.message || "Не удалось экспортировать заявки");
        throw err;
      } finally {
        setIsExporting(false);
      }
    },
    []
  );

  return {
    exportTickets,
    isExporting,
    exportError,
  };
}
