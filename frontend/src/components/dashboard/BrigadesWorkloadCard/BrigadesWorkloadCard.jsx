"use client";

import React from "react";
import styles from "./BrigadesWorkloadCard.module.css";
import { useBrigadesWorkload } from "@/hooks/useBrigadesWorkload";

export default function BrigadesWorkloadCard({ onOpenJournal, onUploadClick }) {
  const { brigades, totalActiveTasks, formattedUpdatedAt, isLoading } = useBrigadesWorkload();

  const hasBrigades = brigades && brigades.length > 0;

  return (
    <div className={styles.card}>
      {/* Хедер */}
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <h2 className={styles.title}>Загрузка бригад</h2>
          <span className={styles.subtitle}>
            Активные задачи относительно рабочей ёмкости · обновлено {formattedUpdatedAt || "14:32"}
          </span>
        </div>

        {isLoading ? (
          <div className={`${styles.skeleton} ${styles.skeletonBadge}`} />
        ) : (
          <div className={styles.badgeTasks}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="7" width="20" height="14" rx="2" ry="2"></rect>
              <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"></path>
            </svg>
            <span>{totalActiveTasks} задач в работе</span>
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

      {/* Шкала и список бригад */}
      <div className={styles.workloadList}>
        {/* Ось шкалы */}
        <div className={styles.scaleRow}>
          <div></div>
          <div className={styles.scaleAxis}>
            <span className={`${styles.scaleMark} ${styles.scaleMarkStart}`}>0</span>
            <span className={styles.scaleMark} style={{ left: "33.3%" }}>4</span>
            <span className={styles.scaleMark} style={{ left: "66.7%" }}>8 - норма</span>
            <span className={`${styles.scaleMark} ${styles.scaleMarkEnd}`}>12 задач</span>
          </div>
          <div></div>
        </div>

        {/* Список строк */}
        {isLoading ? (
          [1, 2, 3, 4, 5].map((i) => (
            <div key={i} className={styles.brigadeRow}>
              <div className={styles.brigadeInfo}>
                <div className={`${styles.skeleton} ${styles.skeletonName}`} />
                <div className={`${styles.skeleton} ${styles.skeletonSub}`} style={{ marginTop: 4 }} />
              </div>
              <div className={`${styles.skeleton} ${styles.skeletonBar}`} />
              <div className={styles.skeleton} style={{ width: 28, height: 14 }} />
            </div>
          ))
        ) : hasBrigades ? (
          brigades.map((brigade) => (
            <div key={brigade.id} className={styles.brigadeRow}>
              <div className={styles.brigadeInfo}>
                <span className={styles.brigadeName}>{brigade.name}</span>
                <span className={styles.brigadeTasks}>
                  {brigade.activeTasks} активных задач
                </span>
              </div>

              <div className={styles.progressTrack}>
                <div
                  className={styles.progressBar}
                  style={{
                    width: `${Math.min(100, brigade.percent)}%`,
                    backgroundColor: brigade.color,
                  }}
                />
              </div>

              <span
                className={styles.percentText}
                style={{ color: brigade.color }}
              >
                {brigade.percent}%
              </span>
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

      {/* Футер */}
      <div className={styles.footer}>
        <button
          type="button"
          className={styles.linkBtn}
          onClick={onOpenJournal}
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
