"use client";

import React, { useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch, API_BASE } from "@/lib/apiFetch";
import { useServiceAreas } from "@/hooks/useServiceAreas";
import styles from "./PlanningModal.module.css";

export default function PlanningModal({ isOpen, onClose, defaultDate }) {
  const queryClient = useQueryClient();
  const { serviceAreas = [] } = useServiceAreas();

  const todayMsk = useMemo(() => {
    return defaultDate || new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
  }, [defaultDate]);

  const [planningDate, setPlanningDate] = useState(todayMsk);
  const [selectedServiceAreaId, setSelectedServiceAreaId] = useState("");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState(null);
  const [planResult, setPlanResult] = useState(null);
  const [applied, setApplied] = useState(false);

  if (!isOpen) return null;

  const handlePreview = async () => {
    setLoading(true);
    setError(null);
    setPlanResult(null);
    setApplied(false);

    try {
      // 1. Загружаем доступные открытые заявки на эту дату
      const ticketsUrl = selectedServiceAreaId
        ? `/tickets?date=${planningDate}&service_area_id=${selectedServiceAreaId}&limit=100`
        : `/tickets?date=${planningDate}&limit=100`;

      const workersUrl = selectedServiceAreaId
        ? `/users?role=worker&limit=50`
        : `/users?role=worker&limit=50`;

      const [tRes, wRes] = await Promise.all([
        apiFetch(ticketsUrl),
        apiFetch(workersUrl),
      ]);

      const tickets = tRes.ok ? await tRes.json() : [];
      const workers = wRes.ok ? await wRes.json() : [];

      const waitingTickets = tickets.filter(
        (t) => t.status === "planned" || !t.assigned_worker_id
      );

      // Планирование в OR-Tools строится в рамках одного участка (service_area_id).
      // Если зона не выбрана, берем первую зону, где есть нераспределенные заявки.
      let effectiveAreaId = selectedServiceAreaId ? Number(selectedServiceAreaId) : null;
      if (!effectiveAreaId) {
        effectiveAreaId = waitingTickets.find((t) => t.service_area_id)?.service_area_id || null;
      }

      const areaTickets = effectiveAreaId
        ? waitingTickets.filter((t) => t.service_area_id === effectiveAreaId)
        : waitingTickets;

      const candidateTickets = areaTickets.map((t) => t.id).slice(0, 100);

      // Специалисты участка (макс. 20 по лимиту бэкенда planning_max_workers)
      const areaWorkers = effectiveAreaId
        ? workers.filter(
            (w) =>
              (w.worker_profile?.service_area_id ?? w.service_area_id) === effectiveAreaId ||
              (!w.worker_profile?.service_area_id && !w.service_area_id)
          )
        : workers;

      const candidateWorkers = (areaWorkers.length > 0 ? areaWorkers : workers)
        .map((w) => w.id)
        .slice(0, 20);

      if (candidateTickets.length === 0) {
        throw new Error(
          effectiveAreaId
            ? `На дату ${planningDate} нет нераспределенных заявок в выбранной зоне обслуживания`
            : `На дату ${planningDate} нет нераспределенных заявок со статусом "Ожидание"`
        );
      }
      if (candidateWorkers.length === 0) {
        throw new Error("В системе нет доступных выездных специалистов");
      }

      const payload = {
        route_date: planningDate,
        ticket_ids: candidateTickets,
        worker_ids: candidateWorkers,
        allow_partial: true,
        ...(effectiveAreaId ? { service_area_id: effectiveAreaId } : {}),
      };

      const res = await apiFetch("/planning/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        let msg = "Не удалось рассчитать план";
        const code = errData?.detail?.code;
        if (code === "multiple_service_areas") {
          msg = "Заявки принадлежат разным участкам обслуживания. Выберите конкретный участок в поле 'Зона обслуживания'.";
        } else if (code === "planning_limit_exceeded") {
          msg = "Превышен лимит заявок (макс. 100) или инженеров (макс. 20) на один расчет плана.";
        } else if (code === "planning_busy") {
          msg = "Сервер планирования сейчас занят другим расчетом. Повторите через несколько секунд.";
        } else if (errData?.detail?.message) {
          msg = errData.detail.message;
        } else if (typeof errData?.detail === "string") {
          msg = errData.detail;
        }
        throw new Error(msg);
      }

      const data = await res.json();
      setPlanResult(data);
    } catch (err) {
      setError(err.message || "Ошибка при расчете планирования");
    } finally {
      setLoading(false);
    }
  };

  const handleApply = async () => {
    if (!planResult?.plan_id) return;
    setApplying(true);
    setError(null);

    try {
      const res = await apiFetch(`/planning/plans/${planResult.plan_id}/apply`, {
        method: "POST",
        body: JSON.stringify({}),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        let msg = "Ошибка применения плана";
        const code = errData?.detail?.code;
        if (code === "plan_has_no_assignments") {
          msg = "В плане нет сформированных маршрутов (0 назначений). Пустой план не может быть сохранён в БД.";
        } else if (code === "plan_expired") {
          msg = "Срок действия расчета истек. Выполните расчет плана заново.";
        } else if (code === "plan_stale") {
          msg = "Данные изменились с момента расчета плана. Выполните повторный расчет.";
        } else if (code === "shift_already_started") {
          msg = "Смена уже началась для одного из выбранных инженеров.";
        } else if (errData?.detail?.message) {
          msg = errData.detail.message;
        } else if (typeof errData?.detail === "string") {
          msg = errData.detail;
        }
        throw new Error(msg);
      }

      setApplied(true);
      // Инвалидируем кэш (FE-04)
      queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
      queryClient.invalidateQueries({ queryKey: ["routesList"] });
      queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
      queryClient.invalidateQueries({ queryKey: ["fastStats"] });
      queryClient.invalidateQueries({ queryKey: ["ticketsSummary"] });
    } catch (err) {
      setError(err.message || "Ошибка при сохранении назначений");
    } finally {
      setApplying(false);
    }
  };

  const handleExport = () => {
    if (!planResult?.plan_id) return;
    window.open(`${API_BASE}/reports/plans/${planResult.plan_id}/export?format=xlsx`, "_blank");
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <div className={styles.iconWrap}>⚡</div>
            <div>
              <h2 className={styles.title}>Автоматическое планирование маршрутов</h2>
              <p className={styles.subtitle}>Расчет оптимального распределения задач и дорожных маршрутов через OR-Tools</p>
            </div>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div className={styles.body}>
          {error && <div className={styles.errorBox}>{error}</div>}

          {/* Параметры */}
          <div className={styles.formRow}>
            <div className={styles.formGroup}>
              <label className={styles.label}>Дата планирования</label>
              <input
                type="date"
                className={styles.input}
                value={planningDate}
                onChange={(e) => setPlanningDate(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.label}>Зона обслуживания</label>
              <select
                className={styles.select}
                value={selectedServiceAreaId}
                onChange={(e) => setSelectedServiceAreaId(e.target.value)}
              >
                <option value="">Все зоны обслуживания</option>
                {serviceAreas.map((sa) => (
                  <option key={sa.id} value={sa.id}>
                    {sa.name} {sa.city ? `(${sa.city})` : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <button
            type="button"
            className={styles.calcBtn}
            onClick={handlePreview}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className={styles.spinner} />
                <span>Идёт расчет маршрутов...</span>
              </>
            ) : (
              "Рассчитать оптимальный план"
            )}
          </button>

          {/* Результаты предпросмотра */}
          {planResult && (
            <div className={styles.resultBox}>
              <div className={styles.resultHeader}>
                <span className={styles.resultTitle}>Сводка плана #{planResult.plan_id.slice(0, 8)}</span>
                <span className={styles.outcomeBadge}>
                  {planResult.outcome === "optimal" ? "Оптимально" : "Рассчитано"}
                </span>
              </div>

              <div className={styles.statsGrid}>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Назначено заявок</span>
                  <span className={styles.statValue}>
                    {planResult.metrics?.assigned_tickets ?? planResult.assigned_tickets?.length ?? 0}
                  </span>
                </div>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Не назначено</span>
                  <span className={styles.statValue}>
                    {planResult.metrics?.unassigned_tickets ?? 0}
                  </span>
                </div>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Задействовано мастеров</span>
                  <span className={styles.statValue}>
                    {planResult.routes?.length ?? planResult.metrics?.active_workers ?? 0}
                  </span>
                </div>
                <div className={styles.statCard}>
                  <span className={styles.statLabel}>Общий километраж</span>
                  <span className={styles.statValue}>
                    {planResult.metrics?.total_travel_distance_km != null
                      ? `${planResult.metrics.total_travel_distance_km.toFixed(1)} км`
                      : "—"}
                  </span>
                </div>
              </div>

              {((planResult.routes?.length ?? 0) === 0 && (planResult.metrics?.assigned_tickets ?? 0) === 0) && (
                <div style={{ padding: "10px 14px", marginTop: "12px", borderRadius: "8px", background: "#fef3c7", color: "#92400e", fontSize: "13px" }}>
                  ⚠️ Маршруты не сформированы (0 назначений). Проверьте доступность инженеров на выбранную дату (смены, график 2/2 или 5/2, зону обслуживания). Пустой план применить нельзя.
                </div>
              )}

              <div className={styles.actionButtons}>
                {!applied ? (
                  <button
                    type="button"
                    className={styles.applyBtn}
                    onClick={handleApply}
                    disabled={applying || ((planResult.routes?.length ?? 0) === 0 && (planResult.metrics?.assigned_tickets ?? 0) === 0)}
                  >
                    {applying ? "Применение..." : "Применить план и выдать маршруты"}
                  </button>
                ) : (
                  <div className={styles.appliedNotice}>
                    ✓ План успешно применён! Маршруты зафиксированы в БД.
                  </div>
                )}

                <button
                  type="button"
                  className={styles.exportBtn}
                  onClick={handleExport}
                >
                  Скачать Excel (.xlsx)
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
