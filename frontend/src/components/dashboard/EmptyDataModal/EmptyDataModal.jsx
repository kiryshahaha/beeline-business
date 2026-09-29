"use client";

import React, { useState, useRef } from "react";
import styles from "./EmptyDataModal.module.css";
import { useImportData } from "@/hooks/useImportData";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";

export default function EmptyDataModal({ isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState("sources"); // 'sources' | 'system'
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isDragOver, setIsDragOver] = useState(false);
  const [step, setStep] = useState("upload"); // 'upload' | 'planning' | 'approval' | 'applying' | 'done'
  const [batchResults, setBatchResults] = useState(null);
  const [importSummary, setImportSummary] = useState(null);
  const [planResult, setPlanResult] = useState(null);
  const fileInputRef = useRef(null);
  const queryClient = useQueryClient();

  const {
    importFile,
    importMultipleFiles,
    isUploading,
    uploadProgress,
    uploadError,
    resetStatus,
  } = useImportData();

  if (!isOpen) return null;

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      setSelectedFiles((prev) => {
        const existingNames = new Set(prev.map((f) => f.name));
        const added = newFiles.filter((f) => !existingNames.has(f.name));
        return [...prev, ...added];
      });
      resetStatus();
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files);
      setSelectedFiles((prev) => {
        const existingNames = new Set(prev.map((f) => f.name));
        const added = droppedFiles.filter((f) => !existingNames.has(f.name));
        return [...prev, ...added];
      });
      resetStatus();
    }
  };

  const handleRemoveFile = (indexToRemove) => {
    setSelectedFiles((prev) => prev.filter((_, idx) => idx !== indexToRemove));
  };

  const handleClearAll = () => {
    setSelectedFiles([]);
    resetStatus();
  };

  const runPlanningFlow = async () => {
    setStep("planning");
    try {
      // Ищем самую свежую дату среди доступных заявок
      const sampleRes = await apiFetch("/tickets?limit=100");
      const sampleTickets = sampleRes.ok ? await sampleRes.json() : [];

      let targetDate = new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
      if (sampleTickets.length > 0) {
        const dates = sampleTickets
          .map((t) => t.visit_window_start?.split("T")[0])
          .filter(Boolean);
        if (dates.length > 0) {
          targetDate = dates[0];
        }
      }

      const [ticketsRes, workersRes] = await Promise.all([
        apiFetch(`/tickets?date=${targetDate}&limit=100`),
        apiFetch("/users?role=worker&limit=50"),
      ]);

      const tickets = ticketsRes.ok ? await ticketsRes.json() : [];
      const workers = workersRes.ok ? await workersRes.json() : [];

      const waitingTickets = tickets.filter(
        (t) => t.status === "planned" || !t.assigned_worker_id
      );

      // Планирование строится по отдельному участку (service_area_id)
      const firstAreaId =
        waitingTickets.find((t) => t.service_area_id)?.service_area_id || null;

      const areaTickets = firstAreaId
        ? waitingTickets.filter((t) => t.service_area_id === firstAreaId)
        : waitingTickets;

      const candidateTickets = areaTickets.map((t) => t.id).slice(0, 100);

      // Специалисты для этого участка (макс. 20 по лимиту бэкенда)
      const areaWorkers = firstAreaId
        ? workers.filter(
            (w) =>
              (w.worker_profile?.service_area_id ?? w.service_area_id) === firstAreaId ||
              (!w.worker_profile?.service_area_id && !w.service_area_id)
          )
        : workers;

      const candidateWorkers = (areaWorkers.length > 0 ? areaWorkers : workers)
        .map((w) => w.id)
        .slice(0, 20);

      if (candidateTickets.length > 0 && candidateWorkers.length > 0) {
        const previewRes = await apiFetch("/planning/preview", {
          method: "POST",
          body: JSON.stringify({
            route_date: targetDate,
            ...(firstAreaId ? { service_area_id: firstAreaId } : {}),
            ticket_ids: candidateTickets,
            worker_ids: candidateWorkers,
            allow_partial: true,
          }),
        });

        if (previewRes.ok) {
          const planData = await previewRes.json();
          setPlanResult(planData);
          setStep("approval");
          return;
        }
      }
    } catch (e) {
      console.warn("Planning preview error in modal:", e);
    }
    // Если автоматическое планирование не сформировалось (например, нет специалистов), завершаем шаг загрузки
    setStep("upload");
  };

  const handleUploadSelected = async () => {
    if (selectedFiles.length === 0) return;
    try {
      const summary = await importMultipleFiles(selectedFiles, {
        isOrganizerSource: activeTab === "sources",
        dryRun: false,
      });
      setBatchResults(summary);
      setImportSummary(summary);
      queryClient.invalidateQueries();

      if (summary.totalCreated > 0) {
        await runPlanningFlow();
      }
    } catch {
      // Обрабатывается хуком useImportData
    }
  };

  const handleUploadDemoData = async () => {
    try {
      const response = await fetch("/data/dataset.zip");
      if (!response.ok) {
        throw new Error("Не удалось загрузить встроенный демонстрационный файл");
      }
      const blob = await response.blob();
      const demoFile = new File([blob], "dataset.zip", { type: "application/zip" });
      setSelectedFiles([demoFile]);
      const data = await importFile(demoFile, { dryRun: false, isOrganizerSource: false });
      setImportSummary(data);
      queryClient.invalidateQueries();
      await runPlanningFlow();
    } catch {
      // Ошибка обрабатывается хуком
    }
  };

  const handleApprovePlan = async () => {
    setStep("applying");
    try {
      if (planResult?.plan_id) {
        await apiFetch(`/planning/plans/${planResult.plan_id}/apply`, {
          method: "POST",
          body: JSON.stringify({}),
        });
      }
    } catch (err) {
      console.warn("Plan apply error:", err);
    } finally {
      queryClient.invalidateQueries();
      setStep("done");
      setTimeout(() => {
        onClose();
        setStep("upload");
        setSelectedFiles([]);
        setPlanResult(null);
        setImportSummary(null);
        setBatchResults(null);
      }, 1000);
    }
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Кнопка закрыть */}
        <button
          type="button"
          className={styles.closeBtn}
          onClick={onClose}
          aria-label="Закрыть"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>

        {step === "upload" && (
          <>
            {/* Заголовок */}
            <div className={styles.headerBlock}>
              <div className={styles.iconWrapper}>
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                </svg>
              </div>
              <h2 className={styles.title}>Загрузка данных в систему</h2>
              <p className={styles.subtitle}>
                Загрузите файлы для наполнения карты заявками, построения маршрутов и запуска автоматического распределения.
              </p>
            </div>

            {/* Две раздельные области (Табы) */}
            <div className={styles.tabsContainer}>
              <button
                type="button"
                className={`${styles.tabButton} ${activeTab === "sources" ? styles.tabButtonActive : ""}`}
                onClick={() => {
                  setActiveTab("sources");
                  resetStatus();
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="16" y1="13" x2="8" y2="13"></line>
                  <line x1="16" y1="17" x2="8" y2="17"></line>
                </svg>
                <span>Выгрузки организатора</span>
              </button>

              <button
                type="button"
                className={`${styles.tabButton} ${activeTab === "system" ? styles.tabButtonActive : ""}`}
                onClick={() => {
                  setActiveTab("system");
                  resetStatus();
                }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
                  <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
                  <line x1="12" y1="22.08" x2="12" y2="12"></line>
                </svg>
                <span>Системный пакет БД</span>
              </button>
            </div>

            {/* Описание активного режима */}
            <div className={styles.tabDescription}>
              {activeTab === "sources" ? (
                <span>
                  <strong>Дневные файлы кейса:</strong> файлы «Синтетические данные» и «Контрольное распределение» по участкам (Восток, Юго-восток, Югоцентр). Поддерживаются <code>.csv</code> (Windows-1251, UTF-8) и <code>.xlsx</code>. Можно выбрать сразу несколько файлов.
                </span>
              ) : (
                <span>
                  <strong>Полный обмен БД:</strong> единый системный архив <code>.zip</code> (с manifest.json) или системный <code>.xlsx</code> со всеми таблицами базы (города, районы, бригады, инженеры, заявки).
                </span>
              )}
            </div>

            {/* Зона Drag & Drop с мультизагрузкой */}
            <div
              className={`${styles.dropZone} ${isDragOver ? styles.dropZoneActive : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setIsDragOver(true);
              }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <svg className={styles.dropIcon} width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
              <span className={styles.dropText}>
                {selectedFiles.length > 0
                  ? `Выбрано файлов: ${selectedFiles.length}`
                  : "Перетащите файлы сюда или нажмите для выбора"}
              </span>
              <span className={styles.dropHint}>
                {activeTab === "sources"
                  ? "Файлы «Синтетические данные» (.csv, .xlsx). Можно выбрать сразу несколько."
                  : "Пакет базы данных (.zip с manifest.json или .xlsx)"}
              </span>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={activeTab === "sources" ? ".csv,.xlsx" : ".zip,.xlsx"}
                className={styles.hiddenInput}
                onChange={handleFileChange}
              />
            </div>

            {/* Список выбранных файлов */}
            {selectedFiles.length > 0 && (
              <div className={styles.filesListContainer}>
                <div className={styles.filesListHeader}>
                  <span>Список к загрузке ({selectedFiles.length})</span>
                  <button type="button" className={styles.clearAllBtn} onClick={handleClearAll}>
                    Очистить всё
                  </button>
                </div>
                {selectedFiles.map((f, idx) => (
                  <div key={idx} className={styles.fileChip}>
                    <div className={styles.fileChipLeft}>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFC800" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                      </svg>
                      <span className={styles.fileChipName} title={f.name}>{f.name}</span>
                      <span className={styles.fileChipSize}>({(f.size / 1024).toFixed(1)} КБ)</span>
                    </div>
                    <button
                      type="button"
                      className={styles.fileChipRemove}
                      onClick={() => handleRemoveFile(idx)}
                      title="Удалить файл из списка"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Детальный отчет по мультизагрузке */}
            {batchResults?.results && batchResults.results.length > 0 && (
              <div className={styles.batchResultsCard}>
                <div style={{ fontWeight: 600, color: "#FFFFFF" }}>
                  Результат импорта: создано {batchResults.totalCreated} заявок
                </div>
                {batchResults.results.map((r, i) => (
                  <div key={i} className={styles.batchResultItem}>
                    <span className={styles.batchResultName} title={r.file}>
                      {r.file}
                    </span>
                    {r.success ? (
                      <span className={styles.badgeSuccess}>
                        +{r.created} заявок
                      </span>
                    ) : (
                      <span className={styles.badgeError} title={r.error}>
                        Ошибка
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Статус / Ошибки */}
            {uploadError && <div className={styles.errorMessage}>{uploadError}</div>}

            {/* Кнопки действий */}
            <div className={styles.actions}>
              {selectedFiles.length > 0 ? (
                <button
                  type="button"
                  className={styles.uploadBtn}
                  onClick={handleUploadSelected}
                  disabled={isUploading}
                >
                  {isUploading ? (
                    <>
                      <div className={styles.buttonSpinner} />
                      <span>
                        {uploadProgress
                          ? `Загрузка ${uploadProgress.current}/${uploadProgress.total}: ${uploadProgress.fileName}`
                          : "Импортируем файлы..."}
                      </span>
                    </>
                  ) : (
                    `Загрузить ${selectedFiles.length > 1 ? `${selectedFiles.length} файла(ов)` : selectedFiles[0].name}`
                  )}
                </button>
              ) : activeTab === "system" ? (
                <button
                  type="button"
                  className={styles.uploadBtn}
                  onClick={handleUploadDemoData}
                  disabled={isUploading}
                >
                  {isUploading ? (
                    <>
                      <div className={styles.buttonSpinner} />
                      <span>Импортируем данные...</span>
                    </>
                  ) : (
                    <>
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                      </svg>
                      <span>Загрузить стандартный демо-набор</span>
                    </>
                  )}
                </button>
              ) : null}

              {activeTab === "sources" && !selectedFiles.length && !isUploading && (
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={handleUploadDemoData}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                  </svg>
                  <span>Загрузить стандартный демо-набор (.zip)</span>
                </button>
              )}

              {!isUploading && (
                <button
                  type="button"
                  className={styles.skipLink}
                  onClick={onClose}
                >
                  Продолжить без загрузки
                </button>
              )}
            </div>
          </>
        )}

        {step === "planning" && (
          <div className={styles.planningState}>
            <div className={styles.pulseIconWrapper}>
              <div className={styles.pulseRings} />
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#FFC800" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon>
              </svg>
            </div>

            <h2 className={styles.title}>Распределяем заявки через планер...</h2>
            <p className={styles.subtitle}>
              Алгоритм OR-Tools рассчитывает дорожные маршруты с учетом смен, навыков специалистов и временных окон визитов.
            </p>

            <div className={styles.progressContainer}>
              <div className={styles.progressBar} />
            </div>

            <div className={styles.planningStatusText}>
              <span>Синхронизация дорожных матриц и окон визитов</span>
            </div>
          </div>
        )}

        {step === "approval" && (
          <div className={styles.approvalState}>
            <div className={styles.headerBlock}>
              <div className={`${styles.iconWrapper} ${styles.iconApproval}`}>
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                  <polyline points="22 4 12 14.01 9 11.01"></polyline>
                </svg>
              </div>
              <h2 className={styles.title}>План распределения готов</h2>
              <p className={styles.subtitle}>
                Оптимальные маршруты рассчитаны. Проверьте сводку и утвердите план для передачи бригадам.
              </p>
            </div>

            {/* Сводка распределения */}
            <div className={styles.metricsSummary}>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Распределено</span>
                <span className={styles.summaryValue}>
                  {planResult?.metrics?.assigned_tickets != null
                    ? `${planResult.metrics.assigned_tickets} заявок`
                    : importSummary?.totalCreated != null
                    ? `${importSummary.totalCreated} заявок`
                    : "Данные загружены"}
                </span>
                <span className={styles.summarySub}>
                  {planResult?.outcome === "optimal" ? "Оптимальный план" : "Готово к выдаче"}
                </span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Задействовано</span>
                <span className={styles.summaryValue}>
                  {planResult?.routes?.length != null
                    ? `${planResult.routes.length} маршрутов`
                    : "Специалисты готовы"}
                </span>
                <span className={styles.summarySub}>Выездная служба</span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Пробег</span>
                <span className={styles.summaryValue}>
                  {planResult?.metrics?.total_travel_distance_km != null
                    ? `${planResult.metrics.total_travel_distance_km.toFixed(1)} км`
                    : "В норме"}
                </span>
                <span className={styles.summarySub}>Оптимизация дорог</span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Статус SLA</span>
                <span className={`${styles.summaryValue} ${styles.slaOk}`}>SLA OK</span>
                <span className={styles.summarySub}>В окнах визитов</span>
              </div>
            </div>

            <div className={styles.approvalNotice}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FFC800" strokeWidth="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="8" x2="12" y2="12"></line>
                <line x1="12" y1="16" x2="12.01" y2="16"></line>
              </svg>
              <span>После утверждения заявки перейдут в статус «Назначена», и исполнители получат путевые листы.</span>
            </div>

            <div className={styles.actions}>
              <button
                type="button"
                className={styles.uploadBtn}
                onClick={handleApprovePlan}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span>Утвердить и выдать маршруты</span>
              </button>

              <button
                type="button"
                className={styles.secondaryBtn}
                onClick={onClose}
              >
                Закрыть и скорректировать позже
              </button>
            </div>
          </div>
        )}

        {(step === "applying" || step === "done") && (
          <div className={styles.planningState}>
            <div className={`${styles.iconWrapper} ${step === "done" ? styles.iconSuccess : ""}`}>
              {step === "applying" ? (
                <div className={styles.spinner} />
              ) : (
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#34C759" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
              )}
            </div>

            <h2 className={styles.title}>
              {step === "applying" ? "Применяем маршруты..." : "План успешно утверждён!"}
            </h2>
            <p className={styles.subtitle}>
              {step === "applying"
                ? "Фиксируем назначения в базе данных и оповещаем бригадиров..."
                : "Маршруты выданы выездным бригадам. Система обновляется."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
