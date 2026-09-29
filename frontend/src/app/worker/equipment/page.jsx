// frontend/src/app/worker/equipment/page.jsx
"use client";

import React, { useState } from "react";
import { useAuth } from "@/providers/AuthProvider";
import { useMyDay } from "@/hooks/worker/useMyDay";
import { useWorkerEquipment } from "@/hooks/worker/useWorkerEquipment";
import { getTodayMsk, getTomorrowMsk } from "@/lib/worker/time";
import styles from "./equipment.module.css";

export default function WorkerEquipmentPage() {
  const { user } = useAuth();
  const todayMsk = getTodayMsk();
  const tomorrowMsk = getTomorrowMsk();
  const [selectedDate, setSelectedDate] = useState(todayMsk);

  const { data: dayData } = useMyDay(selectedDate);
  const { data: equipmentData, isLoading, isError, error, refetch } = useWorkerEquipment(
    user?.id,
    selectedDate
  );

  const office = dayData?.worker?.office;
  const isToday = selectedDate === todayMsk;

  const { items = [], to_issue = [], shortages = [] } = equipmentData || {};

  return (
    <div className={styles.container}>
      {/* Top Header Card */}
      <div className={styles.topCard}>
        <div className={styles.headerTitles}>
          <h1 className={styles.title}>Оборудование и склад</h1>
          <p className={styles.subtitle}>Комплект на день и остатки на руках</p>
        </div>

        {/* Date Toggle */}
        <div className={styles.dateToggle}>
          <button
            type="button"
            className={`${styles.dateBtn} ${isToday ? styles.dateBtnActive : ""}`}
            onClick={() => setSelectedDate(todayMsk)}
          >
            Сегодня
          </button>
          <button
            type="button"
            className={`${styles.dateBtn} ${!isToday ? styles.dateBtnActive : ""}`}
            onClick={() => setSelectedDate(tomorrowMsk)}
          >
            Завтра
          </button>
        </div>
      </div>

      {/* Office Card */}
      {office && (
        <div className={styles.officeCard}>
          <div className={styles.officeIcon}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
              <path d="M9 22v-4h6v4" />
              <path d="M8 6h.01" />
              <path d="M16 6h.01" />
              <path d="M8 10h.01" />
              <path d="M16 10h.01" />
              <path d="M8 14h.01" />
              <path d="M16 14h.01" />
            </svg>
          </div>
          <div className={styles.officeInfo}>
            <span className={styles.officeLabel}>Офис выдачи</span>
            <span className={styles.officeName}>{office.name}</span>
            <span className={styles.officeAddress}>{office.address}</span>
          </div>
        </div>
      )}

      {/* Shortages Alert */}
      {shortages.length > 0 && (
        <div className={styles.shortageBanner}>
          <div className={styles.shortageHeader}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
            <strong>В офисе не хватает оборудования:</strong>
          </div>
          <ul className={styles.shortageList}>
            {shortages.map((s, idx) => (
              <li key={idx}>
                {s.name || s.appliance_name} — не хватает {s.quantity || s.shortage} {s.unit || "шт."}
              </li>
            ))}
          </ul>
        </div>
      )}

      {isLoading && (
        <div className={styles.loadingBox}>Загрузка данных об оборудовании...</div>
      )}

      {isError && (
        <div className={styles.errorBox}>
          <div>Ошибка загрузки оборудования: {error?.message}</div>
          <button type="button" className={styles.retryBtn} onClick={() => refetch()}>
            Повторить
          </button>
        </div>
      )}

      {!isLoading && !isError && (
        <>
          {/* Responsive 2-Column Grid on Tablet/Desktop */}
          <div className={styles.equipmentGrid}>
            {/* TO ISSUE (Получить в офисе) */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Получить в офисе ({to_issue.length})</h2>
                <span className={styles.readOnlyBadge}>Выдаёт диспетчер</span>
              </div>

              {to_issue.length === 0 ? (
                <div className={styles.emptyCard}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ display: "inline-block", verticalAlign: "middle", marginRight: 6 }}>
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Весь комплект выдан либо заявки не требуют получения
                </div>
              ) : (
                <div className={styles.itemList}>
                  {to_issue.map((item, idx) => {
                    const isTicketPurpose = item.purpose === "ticket";
                    return (
                      <div key={idx} className={styles.itemRow}>
                        <div className={styles.itemMain}>
                          <div className={styles.itemName}>{item.name}</div>
                          <div className={styles.itemPurpose}>
                            {isTicketPurpose && item.ticket_id
                              ? `Под заявку №${item.ticket_id}`
                              : isTicketPurpose
                              ? "Под заявку"
                              : "Свободный резерв"}
                          </div>
                        </div>
                        <div className={styles.itemQtyBadge}>
                          {item.quantity} {item.unit || "шт."}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            {/* ON HAND (На руках) */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>На руках у инженера ({items.length})</h2>
              </div>

              {items.length === 0 ? (
                <div className={styles.emptyCard}>
                  На руках ничего не числится
                </div>
              ) : (
                <div className={styles.itemList}>
                  {items.map((item, idx) => (
                    <div key={idx} className={styles.itemRow}>
                      <div className={styles.itemMain}>
                        <div className={styles.itemName}>{item.name}</div>
                        <div className={styles.itemMeta}>
                          <span>Зарезервировано: <strong>{item.committed}</strong></span>
                          <span>·</span>
                          <span>Свободно: <strong>{item.free}</strong></span>
                        </div>
                      </div>
                      <div className={styles.totalOnHand}>
                        <span className={styles.onHandValue}>{item.on_hand}</span>
                        <span className={styles.onHandLabel}>всего</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <div className={styles.infoNote}>
            ℹ️ Оформление выдачи и возврата оборудования выполняется диспетчером или кладовщиком в офисе.
          </div>
        </>
      )}
    </div>
  );
}
