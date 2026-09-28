"use client";

import React, { useState, useRef } from "react";
import styles from "./EmptyDataModal.module.css";
import { useImportData } from "@/hooks/useImportData";
import { useQueryClient } from "@tanstack/react-query";

export default function EmptyDataModal({ isOpen, onClose }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [step, setStep] = useState("upload"); // 'upload' | 'planning' | 'approval' | 'applying' | 'done'
  const fileInputRef = useRef(null);
  const queryClient = useQueryClient();

  const { importFile, isUploading, uploadError, uploadSuccess } = useImportData();

  if (!isOpen) return null;

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setSelectedFile(e.dataTransfer.files[0]);
    }
  };

  const runPlanningFlow = () => {
    setStep("planning");
    setTimeout(() => {
      setStep("approval");
    }, 1400);
  };

  const handleUploadSelected = async () => {
    if (!selectedFile) return;
    try {
      await importFile(selectedFile, { dryRun: false });
      runPlanningFlow();
    } catch {
      // Ошибка обрабатывается хуком useImportData
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
      setSelectedFile(demoFile);
      await importFile(demoFile, { dryRun: false });
      runPlanningFlow();
    } catch {
      // Ошибка обрабатывается хуком
    }
  };

  const handleApprovePlan = () => {
    setStep("applying");
    setTimeout(() => {
      // Инвалидируем все запросы, чтобы дашборд и карта обновились
      queryClient.invalidateQueries({ queryKey: ["fastStats"] });
      queryClient.invalidateQueries({ queryKey: ["ticketsSummary"] });
      queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
      queryClient.invalidateQueries({ queryKey: ["recentActivity"] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["routes"] });

      setStep("done");
      setTimeout(() => {
        onClose();
        setStep("upload");
        setSelectedFile(null);
      }, 1000);
    }, 800);
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
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
                </svg>
              </div>
              <h2 className={styles.title}>В базе данных пока нет данных</h2>
              <p className={styles.subtitle}>
                Чтобы наполнить дашборд реальными метриками, графиками загрузки бригад и лентой событий, загрузите файл с заявками (.csv, .xlsx или .zip).
              </p>
            </div>

            {/* Drag & Drop область */}
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
              <svg className={styles.dropIcon} width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="17 8 12 3 7 8"></polyline>
                <line x1="12" y1="3" x2="12" y2="15"></line>
              </svg>
              <span className={styles.dropText}>
                {selectedFile ? selectedFile.name : "Выберите или перетащите файл"}
              </span>
              <span className={styles.dropHint}>Поддерживаются форматы: .csv, .xlsx, .zip архивы</span>
              <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.zip"
                className={styles.hiddenInput}
                onChange={handleFileChange}
              />
            </div>

            {/* Статус / Ошибки */}
            {uploadError && <div className={styles.errorMessage}>{uploadError}</div>}

            {/* Кнопки действий */}
            <div className={styles.actions}>
              {selectedFile ? (
                <button
                  type="button"
                  className={styles.uploadBtn}
                  onClick={handleUploadSelected}
                  disabled={isUploading}
                >
                  {isUploading ? (
                    <>
                      <div className={styles.buttonSpinner} />
                      <span>Импортируем данные...</span>
                    </>
                  ) : (
                    `Загрузить ${selectedFile.name}`
                  )}
                </button>
              ) : (
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
              )}

              {/* Нижняя кнопка показывается ТОЛЬКО когда нет активной загрузки */}
              {selectedFile && !isUploading && (
                <button
                  type="button"
                  className={styles.secondaryBtn}
                  onClick={handleUploadDemoData}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon>
                  </svg>
                  <span>Или загрузить стандартный демо-набор</span>
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

            <h2 className={styles.title}>Распределяем заявки...</h2>
            <p className={styles.subtitle}>
              Алгоритм OR-Tools рассчитывает дорожные маршруты с учетом смен, навыков специалистов и наличия оборудования.
            </p>

            <div className={styles.progressContainer}>
              <div className={styles.progressBar} />
            </div>

            <div className={styles.planningStatusText}>
              <span>Синхронизация дорожных матриц и временных окон</span>
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
                <span className={styles.summaryValue}>1 500 заявок</span>
                <span className={styles.summarySub}>100% покрытие</span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Задействовано</span>
                <span className={styles.summaryValue}>12 бригад</span>
                <span className={styles.summarySub}>120 специалистов</span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Маршруты</span>
                <span className={styles.summaryValue}>896 выездов</span>
                <span className={styles.summarySub}>Геопривязка СПб</span>
              </div>
              <div className={styles.summaryItem}>
                <span className={styles.summaryLabel}>Статус SLA</span>
                <span className={`${styles.summaryValue} ${styles.slaOk}`}>SLA OK</span>
                <span className={styles.summarySub}>Без задержек</span>
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
                : "Маршруты выданы выездным бригадам. Дашборд обновляется."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

