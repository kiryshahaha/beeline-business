"use client";

import React, { useState } from "react";
import styles from "./ReportsExportSection.module.css";
import {
  useReportConfig,
  REPORT_STATUS_OPTIONS,
  CITIES_OPTIONS,
  PERIOD_OPTIONS,
} from "@/hooks/useReportConfig";

export default function ReportsExportSection() {
  const [filterSearch, setFilterSearch] = useState("");

  const {
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
  } = useReportConfig();

  const filteredAreas = (serviceAreas || []).filter((a) =>
    !filterSearch || a.name.toLowerCase().includes(filterSearch.toLowerCase())
  );

  const filteredBrigades = (brigades || []).filter((b) =>
    !filterSearch || b.name.toLowerCase().includes(filterSearch.toLowerCase())
  );

  return (
    <div className={styles.section}>
      {/* Хедер секции */}
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <h2 className={styles.title}>Выгрузка отчётов</h2>
          <span className={styles.subtitle}>
            Сформируйте детализированный реестр заявок с учётом текущих фильтров
          </span>
        </div>

        <div className={styles.searchFilterGroup}>
          <div className={styles.searchBox}>
            <svg
              className={styles.searchIcon}
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="11" cy="11" r="8"></circle>
              <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input
              type="text"
              placeholder="Фильтр по районам/бригадам..."
              className={styles.searchInput}
              value={filterSearch}
              onChange={(e) => setFilterSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Панель селектов (5 колонок) */}
      <div className={styles.filtersGrid}>
        {/* Селект 1: Город */}
        <div className={styles.filterField}>
          <label className={styles.fieldLabel}>Город</label>
          <div className={styles.selectWrapper}>
            <select
              className={styles.select}
              value={selectedCityId}
              onChange={(e) => setSelectedCityId(e.target.value)}
            >
              {CITIES_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
            <svg className={styles.selectChevron} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
        </div>

        {/* Селект 2: Район */}
        <div className={styles.filterField}>
          <label className={styles.fieldLabel}>Район</label>
          <div className={styles.selectWrapper}>
            <select
              className={styles.select}
              value={selectedAreaId}
              onChange={(e) => setSelectedAreaId(e.target.value)}
            >
              <option value="">Все районы</option>
              {filteredAreas.map((area) => (
                <option key={area.id} value={area.id}>
                  {area.name}
                </option>
              ))}
            </select>
            <svg className={styles.selectChevron} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
        </div>

        {/* Селект 3: Бригада */}
        <div className={styles.filterField}>
          <label className={styles.fieldLabel}>Бригада</label>
          <div className={styles.selectWrapper}>
            <select
              className={styles.select}
              value={selectedBrigadeId}
              onChange={(e) => setSelectedBrigadeId(e.target.value)}
            >
              <option value="">Все бригады</option>
              {filteredBrigades.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
            <svg className={styles.selectChevron} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
        </div>

        {/* Селект 4: Статус */}
        <div className={styles.filterField}>
          <label className={styles.fieldLabel}>Статус</label>
          <div className={styles.selectWrapper}>
            <select
              className={styles.select}
              value={selectedStatus}
              onChange={(e) => setSelectedStatus(e.target.value)}
            >
              {REPORT_STATUS_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <svg className={styles.selectChevron} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
        </div>

        {/* Селект 5: Период */}
        <div className={styles.filterField}>
          <label className={styles.fieldLabel}>Период</label>
          <div className={styles.selectWrapper}>
            <select
              className={styles.select}
              value={selectedPeriod}
              onChange={(e) => setSelectedPeriod(e.target.value)}
            >
              {PERIOD_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            <svg className={styles.selectChevron} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </div>
        </div>
      </div>

      {/* Ошибка если была */}
      {exportError && (
        <div className={styles.errorMessage}>{exportError}</div>
      )}

      {/* Карточка сформированного отчёта */}
      <div className={styles.reportCard}>
        <div className={styles.reportInfo}>
          <div className={styles.reportTitleRow}>
            <span className={styles.reportTitle}>
              Отчёт по заявкам · {periodLabel}
            </span>
            <div className={styles.readyBadge}>
              <span className={styles.readyDot}></span>
              <span>Готов к выгрузке</span>
            </div>
          </div>

          <div className={styles.reportDescription}>
            {cityName} · {areaName} · {brigadeName} ·{" "}
            <strong>{isCountLoading ? "…" : recordsCount} записей</strong> · время в отчёте: Europe/Moscow (UTC+3)
          </div>

          <div className={styles.reportSubtext}>
            Включены русские названия статусов, категорий и состояний, адрес, SLA, ФИО инженера и бригада.
          </div>
        </div>

        <div className={styles.actionsRow}>
          <button
            type="button"
            className={styles.csvBtn}
            onClick={handleDownloadCSV}
            disabled={isExporting}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>{isExporting ? "Выгрузка..." : "Скачать CSV"}</span>
          </button>

          <button
            type="button"
            className={styles.xlsxBtn}
            onClick={handleDownloadXLSX}
            disabled={isExporting}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
              <polyline points="7 10 12 15 17 10"></polyline>
              <line x1="12" y1="15" x2="12" y2="3"></line>
            </svg>
            <span>{isExporting ? "Выгрузка..." : "Скачать XLSX"}</span>
          </button>
        </div>
      </div>

      {/* Сноска */}
      <div className={styles.footnote}>
        Файл формируется по актуальным данным системы с разделителем «;» (для CSV) и автоформатированием ячеек (для Excel).
      </div>
    </div>
  );
}
