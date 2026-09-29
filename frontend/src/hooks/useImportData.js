import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";

export function useImportData() {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [uploadProgress, setUploadProgress] = useState(null);
  const queryClient = useQueryClient();

  const importSingleFile = useCallback(
    async (file, { isOrganizerSource = false, dryRun = false, entity } = {}) => {
      const formData = new FormData();
      formData.append("file", file);

      const fileName = file.name || "";
      const isSource =
        isOrganizerSource ||
        /синтетическ|контрольн|demand|control/i.test(fileName) ||
        (!fileName.toLowerCase().endsWith(".zip") && !fileName.toLowerCase().endsWith(".xlsx") && !entity);

      let endpoint;
      if (isSource) {
        endpoint = `/data/sources/import?dry_run=${dryRun}&geocode=false`;
      } else {
        const urlParams = new URLSearchParams({
          dry_run: String(dryRun),
        });
        if (entity) {
          urlParams.append("entity", entity);
        }
        endpoint = `/data/import?${urlParams}`;
      }

      const res = await apiFetch(endpoint, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        let msg = `Ошибка импорта (${res.status})`;
        try {
          const errData = await res.json();
          if (errData?.detail) {
            if (typeof errData.detail === "string") {
              msg = errData.detail;
            } else if (errData.detail.message) {
              msg = errData.detail.message;
            } else {
              msg = JSON.stringify(errData.detail);
            }
          } else if (errData?.message) {
            msg = errData.message;
          }
        } catch {
          // body parse fallback
        }
        throw new Error(msg);
      }

      return res.json();
    },
    []
  );

  const importFile = useCallback(
    async (file, options = {}) => {
      if (!file) throw new Error("Файл не выбран");
      setIsUploading(true);
      setUploadError(null);
      setUploadSuccess(null);
      setUploadProgress(null);

      try {
        const data = await importSingleFile(file, options);
        setUploadSuccess(data);
        queryClient.invalidateQueries();
        return data;
      } catch (err) {
        const msg = err.message || "Ошибка загрузки файла";
        setUploadError(msg);
        throw err;
      } finally {
        setIsUploading(false);
      }
    },
    [importSingleFile, queryClient]
  );

  const importMultipleFiles = useCallback(
    async (files, options = {}) => {
      if (!files || files.length === 0) throw new Error("Файлы не выбраны");
      setIsUploading(true);
      setUploadError(null);
      setUploadSuccess(null);

      const results = [];
      let totalCreated = 0;
      let hasErrors = false;

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        setUploadProgress({
          current: i + 1,
          total: files.length,
          fileName: file.name,
        });

        try {
          const data = await importSingleFile(file, options);
          const createdCount =
            data?.counts?.created != null
              ? data.counts.created
              : data?.counts
              ? Object.values(data.counts).reduce((acc, v) => acc + (typeof v === "number" ? v : 0), 0)
              : 0;
          totalCreated += createdCount;
          results.push({
            file: file.name,
            success: true,
            created: createdCount,
            data,
          });
        } catch (err) {
          hasErrors = true;
          results.push({
            file: file.name,
            success: false,
            error: err.message,
          });
        }
      }

      queryClient.invalidateQueries();
      setIsUploading(false);
      setUploadProgress(null);

      const summary = {
        results,
        totalFiles: files.length,
        totalCreated,
        hasErrors,
      };

      if (hasErrors && results.every((r) => !r.success)) {
        setUploadError("Не удалось загрузить выбранные файлы");
      } else {
        setUploadSuccess(summary);
      }

      return summary;
    },
    [importSingleFile, queryClient]
  );

  return {
    importFile,
    importMultipleFiles,
    isUploading,
    uploadProgress,
    uploadError,
    uploadSuccess,
    resetStatus: () => {
      setUploadError(null);
      setUploadSuccess(null);
      setUploadProgress(null);
    },
  };
}
