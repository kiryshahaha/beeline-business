"use client";

import React from "react";
import styles from "./BrigadesWorkloadCard.module.css";
import { useBrigadesWorkload } from "@/hooks/useBrigadesWorkload";

export default function BrigadesWorkloadCard({
  onOpenJournal,
  onUploadClick,
  date,
  date_from,
  date_to,
  periodLabel,
}) {
  const { brigades, totalActiveTasks, formattedUpdatedAt, isLoading } = useBrigadesWorkload({
    date,
    date_from,
    date_to,
  });

  const hasBrigades = brigades && brigades.length > 0;
  const isPeriod = Boolean(date_from && date_to) || !date;

  return (
    <div className={styles.card}>
      {/* Хедер */}
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h2 className={styles.title}>Загрузка бригад</h2>
            {periodLabel && (
              <span
                style={{
                  background: "rgba(255, 200, 0, 0.15)",
                  color: "var(--beeline, #ffc800)",
                  fontSize: "11px",
                  fontWeight: 700,
                  padding: "1px 7px",
                  borderRadius: "6px",
                  border: "1px solid rgba(255, 200, 0, 0.25)",
                }}
              >
                {periodLabel}
              </span>
            )}
          </div>
          <span className={styles.subtitle}>
            {isPeriod
              ? `Среднее распределение нагрузки по сменам · обновлено ${formattedUpdatedAt || "14:32"}`
              : `Активные задачи относительно рабочей ёмкости · обновлено ${formattedUpdatedAt || "14:32"}`}
          </span>
        </div>

        {isLoading ? (
          <div className={`${styles.skeleton} ${styles.skeletonBadge}`} />
        ) : (
          <div className={styles.badgeTasks} title={`Суммарно по всем ${brigades.length} бригадам`}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
            </svg>
            <span>
              {isPeriod
                ? `Всего: ~${totalActiveTasks} з./день (~${brigades.length > 0 ? Math.round(totalActiveTasks / brigades.length) : 0} на бригаду)`
                : `Всего: ${totalActiveTasks} задач (~${brigades.length > 0 ? Math.round(totalActiveTasks / brigades.length) : 0} на бригаду)`}
            </span>
          </div>
        )}
      </div>

      {/* Легенда */}
      <div className={styles.legend}>
        <div className={styles.legendItem}>
          <span className={`${styles.dot} ${styles.dotFree}`}></span>
          <span>Свободна · 0–50%</span>
        </div>
        <div className={styles.legendItem}>
          <span className={`${styles.dot} ${styles.dotOptimal}`}></span>
          <span>Оптимально · 51–80%</span>
        </div>
        <div className={styles.legendItem}>
          <span className={`${styles.dot} ${styles.dotOverloaded}`}></span>
          <span>Перегружена · &gt;80%</span>
        </div>
      </div>

      {/* Вертикальный график загрузки бригад */}
      <div className={styles.chartContainer}>
        {/* Горизонтальные уровни шкалы с пунктирными линиями */}
        <div className={styles.yAxisGuide}>
          <div className={`${styles.guideLineRow} ${styles.guideLineRow100}`}>
            <span className={styles.guideLabel}>100%</span>
            <div className={styles.guideLine} />
          </div>
          <div className={`${styles.guideLineRow} ${styles.guideLineRowOverloaded}`}>
            <span className={`${styles.guideLabel} ${styles.guideLabelOverloaded}`}>80% (перегруз)</span>
            <div className={`${styles.guideLine} ${styles.guideLineOverloaded}`} />
          </div>
          <div className={`${styles.guideLineRow} ${styles.guideLineRowNorm}`}>
            <span className={`${styles.guideLabel} ${styles.guideLabelNorm}`}>50% (норма)</span>
            <div className={`${styles.guideLine} ${styles.guideLineNorm}`} />
          </div>
          <div className={`${styles.guideLineRow} ${styles.guideLineRow0}`}>
            <span className={styles.guideLabel}>0%</span>
            <div className={styles.guideLine} />
          </div>
        </div>

        {/* Столбцы бригад */}
        <div className={styles.columnsWrapper}>
          {isLoading ? (
            [1, 2, 3, 4, 5, 6].map((i) => (
              <div key={i} className={styles.columnItem}>
                <div className={`${styles.skeleton} ${styles.skeletonTopVal}`} />
                <div className={styles.colTrack}>
                  <div className={`${styles.skeleton} ${styles.skeletonCol}`} />
                </div>
                <div className={`${styles.skeleton} ${styles.skeletonColLabel}`} />
                <div className={`${styles.skeleton} ${styles.skeletonColSub}`} />
                <div className={`${styles.skeleton} ${styles.skeletonColSub2}`} />
              </div>
            ))
          ) : hasBrigades ? (
            brigades.map((brigade) => (
              <div key={brigade.id} className={styles.columnItem}>
                {/* Значение в процентах сверху над столбцом */}
                <span className={styles.colPercent} style={{ color: brigade.color }}>
                  {brigade.percent}%
                </span>

                {/* Вертикальный трек и столбец */}
                <div
                  className={styles.colTrack}
                  title={`${brigade.name}: ${brigade.activeTasks} зад.${brigade.workers ? ` на ${brigade.workers} чел.` : ""} (загрузка смены: ${brigade.percent}%)`}
                >
                  <div
                    className={styles.colBar}
                    style={{
                      height: `${Math.min(100, Math.max(8, brigade.percent))}%`,
                      backgroundColor: brigade.color,
                    }}
                  />
                </div>

                {/* Подпись бригады снизу */}
                <div className={styles.colInfo}>
                  <span className={styles.colName} title={brigade.name}>
                    {brigade.name.replace(/^Синтетическая\s+/, "")}
                  </span>
                  <span className={styles.colTasks} title={`${brigade.activeTasks} задач в работе`}>
                    {brigade.activeTasks} зад.
                  </span>
                  {brigade.workers ? (
                    <span className={styles.colWorkers} title={`В бригаде ${brigade.workers} сотрудников`}>
                      {brigade.workers} чел.
                    </span>
                  ) : null}
                </div>
              </div>
            ))
          ) : (
            <div className={styles.emptyState}>
              <p>Нет активных бригад в базе данных</p>
              {onUploadClick && (
                <button
                  type="button"
                  className={styles.emptyActionBtn}
                  onClick={onUploadClick}
                >
                  Загрузить данные CSV
                </button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Футер */}
      <div className={styles.footer}>
        <button
          type="button"
          className={styles.linkBtn}
          onClick={onOpenJournal}
          title="Открыть журнал бригад"
        >
          <span>Открыть журнал бригад</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
          </svg>
        </button>
      </div>
    </div>
  );
}
