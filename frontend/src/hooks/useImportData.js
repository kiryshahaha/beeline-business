import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";

export function useImportData() {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const queryClient = useQueryClient();

  const importFile = useCallback(
    async (file, { dryRun = false, entity } = {}) => {
      if (!file) {
        throw new Error("Файл не выбран");
      }

      setIsUploading(true);
      setUploadError(null);
      setUploadSuccess(null);

      try {
        const formData = new FormData();
        formData.append("file", file);

        const urlParams = new URLSearchParams({
          dry_run: String(dryRun),
        });
        if (entity) {
          urlParams.append("entity", entity);
        }

        const res = await apiFetch(`/data/import?${urlParams}`, {
          method: "POST",
          body: formData,
        });

        if (!res.ok) {
          let msg = `Ошибка импорта (${res.status})`;
          try {
            const errData = await res.json();
            if (errData?.detail) {
              msg = typeof errData.detail === "string" ? errData.detail : JSON.stringify(errData.detail);
            }
          } catch {
            // body parse fallback
          }
          throw new Error(msg);
        }

        const data = await res.json();
        setUploadSuccess(data);

        // Инвалидируем все связанные кэши данных для немедленного обновления UI
        queryClient.invalidateQueries();

        return data;
      } catch (err) {
        const message = err.message || "Ошибка загрузки файла";
        setUploadError(message);
        throw err;
      } finally {
        setIsUploading(false);
      }
    },
    [queryClient]
  );

  return {
    importFile,
    isUploading,
    uploadError,
    uploadSuccess,
    resetStatus: () => {
      setUploadError(null);
      setUploadSuccess(null);
    },
  };
}
