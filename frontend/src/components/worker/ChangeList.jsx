// frontend/src/components/worker/ChangeList.jsx
"use client";

import React from "react";
import { formatMskDateTime } from "@/lib/worker/time";
import { CHANGE_KIND_LABELS, CHANGE_SOURCE_LABELS } from "@/lib/worker/labels";
import styles from "./ChangeList.module.css";

export default function ChangeList({ changes = [] }) {
  if (!changes || changes.length === 0) {
    return <div className={styles.empty}>История изменений пуста</div>;
  }

  return (
    <div className={styles.list}>
      {changes.map((item, index) => {
        const kindLabel = CHANGE_KIND_LABELS[item.kind] || item.kind;
        const sourceLabel = CHANGE_SOURCE_LABELS[item.source] || item.source || "система";
        const reason = item.reason_text || item.reason || "причина не указана";
        const timeStr = formatMskDateTime(item.at || item.occurred_at || item.created_at);

        return (
          <div key={item.id || index} className={styles.item}>
            <div className={styles.bullet} />
            <div className={styles.content}>
              <div className={styles.headerRow}>
                <span className={styles.kind}>{kindLabel}</span>
                <span className={styles.time}>{timeStr}</span>
              </div>
              <div className={styles.source}>
                Источник: <span className={styles.sourceHighlight}>{sourceLabel}</span>
              </div>
              <div className={styles.reason}>
                {reason}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
