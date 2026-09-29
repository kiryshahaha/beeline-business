"use client";

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import { useAvailableDates } from "@/hooks/useAvailableDates";
import styles from "./DatePicker.module.css";

// Вспомогательные функции для работы со строками YYYY-MM-DD
function getMskTodayStr() {
  return new Date().toLocaleDateString("en-CA", { timeZone: "Europe/Moscow" });
}

function shiftDays(dateStr, days) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

function formatHumanMskDate(dateStr) {
  if (!dateStr) return "";
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const months = [
    "янв", "фев", "мар", "апр", "май", "июн",
    "июл", "авг", "сен", "окт", "ноя", "дек"
  ];
  return `${d} ${months[dt.getUTCMonth()]}`;
}

export default function DatePicker({
  value, // { mode: 'single' | 'range' | 'all', date: 'YYYY-MM-DD', from: 'YYYY-MM-DD', to: 'YYYY-MM-DD' }
  onChange,
  singleOnly = false,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const [hoverDate, setHoverDate] = useState(null);
  const wrapperRef = useRef(null);

  const todayStr = useMemo(() => getMskTodayStr(), []);
  const { dateCounts, hasToday, closestDate } = useAvailableDates(todayStr);
  const effectiveMode = singleOnly ? "single" : (value?.mode || "single");

  // Текущий просматриваемый месяц в календаре (год и месяц 0..11)
  const [viewYear, setViewYear] = useState(() => {
    const base = value?.date || value?.from || todayStr;
    return Number(base.slice(0, 4));
  });
  const [viewMonth, setViewMonth] = useState(() => {
    const base = value?.date || value?.from || todayStr;
    return Number(base.slice(5, 7)) - 1;
  });

  // Автоматическая синхронизация просматриваемого месяца при изменении даты
  useEffect(() => {
    const base = value?.date || value?.from;
    if (base && base.length >= 7) {
      queueMicrotask(() => {
        setViewYear(Number(base.slice(0, 4)));
        setViewMonth(Number(base.slice(5, 7)) - 1);
      });
    }
  }, [value?.date, value?.from]);

  // Автоматический выбор ближайшего доступного дня, если на сегодня нет задач
  useEffect(() => {
    if (!value?.date || value.date === todayStr) {
      if (!hasToday && closestDate && closestDate !== todayStr) {
        queueMicrotask(() => {
          onChange?.({
            mode: "single",
            date: closestDate,
            from: closestDate,
            to: closestDate,
          });
        });
      }
    }
  }, [value?.date, todayStr, hasToday, closestDate, onChange]);

  // Закрытие по клику вне календаря и по Escape
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };

    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  // Переключение месяца
  const prevMonth = (e) => {
    e.stopPropagation();
    if (viewMonth === 0) {
      setViewMonth(11);
      setViewYear((y) => y - 1);
    } else {
      setViewMonth((m) => m - 1);
    }
  };

  const nextMonth = (e) => {
    e.stopPropagation();
    if (viewMonth === 11) {
      setViewMonth(0);
      setViewYear((y) => y + 1);
    } else {
      setViewMonth((m) => m + 1);
    }
  };

  // Быстрое переключение на шаг назад / вперед (в режиме single)
  const stepSingleDay = useCallback((step, e) => {
    e.stopPropagation();
    const cur = value?.date || todayStr;
    const next = shiftDays(cur, step);
    onChange({
      mode: "single",
      date: next,
      from: next,
      to: next,
    });
  }, [value?.date, todayStr, onChange]);

  // Генерация дней для текущей сетки месяца
  const calendarDays = useMemo(() => {
    const firstDayOfMonth = new Date(Date.UTC(viewYear, viewMonth, 1));
    const lastDayOfMonth = new Date(Date.UTC(viewYear, viewMonth + 1, 0));
    const totalDays = lastDayOfMonth.getUTCDate();

    // День недели первого дня (0 - Вс, 1 - Пн, ..., 6 - Сб)
    let startDayOfWeek = firstDayOfMonth.getUTCDay();
    // Переводим в формат: 0 - Пн ... 6 - Вс
    startDayOfWeek = startDayOfWeek === 0 ? 6 : startDayOfWeek - 1;

    const days = [];

    // Дни предыдущего месяца для заполнения первой недели
    const prevMonthLastDay = new Date(Date.UTC(viewYear, viewMonth, 0)).getUTCDate();
    for (let i = startDayOfWeek - 1; i >= 0; i--) {
      const d = prevMonthLastDay - i;
      const prevDate = new Date(Date.UTC(viewYear, viewMonth - 1, d));
      days.push({
        dateStr: prevDate.toISOString().slice(0, 10),
        dayNum: d,
        isCurrentMonth: false,
      });
    }

    // Дни текущего месяца
    for (let d = 1; d <= totalDays; d++) {
      const curDate = new Date(Date.UTC(viewYear, viewMonth, d));
      days.push({
        dateStr: curDate.toISOString().slice(0, 10),
        dayNum: d,
        isCurrentMonth: true,
      });
    }

    // Дни следующего месяца до завершения строки (кратность 7)
    const remaining = (7 - (days.length % 7)) % 7;
    for (let d = 1; d <= remaining; d++) {
      const nextDate = new Date(Date.UTC(viewYear, viewMonth + 1, d));
      days.push({
        dateStr: nextDate.toISOString().slice(0, 10),
        dayNum: d,
        isCurrentMonth: false,
      });
    }

    return days;
  }, [viewYear, viewMonth]);

  // Обработка клика по конкретному дню в сетке
  const handleDayClick = (dateStr) => {
    if (singleOnly || effectiveMode === "single" || effectiveMode === "all") {
      onChange({
        mode: "single",
        date: dateStr,
        from: dateStr,
        to: dateStr,
      });
      setIsOpen(false);
      return;
    }

    // Режим "range"
    if (!value?.from || (value?.from && value?.to)) {
      // Начинаем новый выбор диапазона
      onChange({
        mode: "range",
        date: dateStr,
        from: dateStr,
        to: null,
      });
    } else {
      // Завершаем выбор диапазона
      let from = value.from;
      let to = dateStr;
      if (from > to) {
        [from, to] = [to, from];
      }
      onChange({
        mode: "range",
        date: from,
        from,
        to,
      });
      setIsOpen(false);
    }
  };

  // Пресеты
  const selectPreset = (presetKey) => {
    if (presetKey === "today") {
      onChange({ mode: "single", date: todayStr, from: todayStr, to: todayStr });
      setIsOpen(false);
    } else if (presetKey === "yesterday") {
      const y = shiftDays(todayStr, -1);
      onChange({ mode: "single", date: y, from: y, to: y });
      setIsOpen(false);
    } else if (presetKey === "tomorrow") {
      const t = shiftDays(todayStr, 1);
      onChange({ mode: "single", date: t, from: t, to: t });
      setIsOpen(false);
    } else if (!singleOnly && presetKey === "week") {
      const end = shiftDays(todayStr, 6);
      onChange({ mode: "range", date: todayStr, from: todayStr, to: end });
      setIsOpen(false);
    } else if (!singleOnly && presetKey === "month") {
      const from = `${todayStr.slice(0, 7)}-01`;
      const [year, month] = todayStr.split("-").map(Number);
      const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
      const to = `${todayStr.slice(0, 7)}-${String(lastDay).padStart(2, "0")}`;
      onChange({ mode: "range", date: from, from, to });
      setIsOpen(false);
    } else if (!singleOnly && presetKey === "all") {
      onChange({ mode: "all", date: null, from: null, to: null });
      setIsOpen(false);
    }
  };

  // Текст на триггере
  const triggerLabel = useMemo(() => {
    if (effectiveMode === "all") {
      return "Все даты";
    }
    if (effectiveMode === "single") {
      const d = value?.date || todayStr;
      if (d === todayStr) return `Сегодня, ${formatHumanMskDate(d)}`;
      if (d === shiftDays(todayStr, -1)) return `Вчера, ${formatHumanMskDate(d)}`;
      if (d === shiftDays(todayStr, 1)) return `Завтра, ${formatHumanMskDate(d)}`;
      return `${formatHumanMskDate(d)} ${d.slice(0, 4)}`;
    }
    if (effectiveMode === "range") {
      if (value?.from && value?.to) {
        return `${formatHumanMskDate(value.from)} — ${formatHumanMskDate(value.to)}`;
      }
      if (value?.from) {
        return `С ${formatHumanMskDate(value.from)}...`;
      }
      return "Период";
    }
    return "Дата";
  }, [effectiveMode, value, todayStr]);

  // Количество дней в диапазоне (для бейджа)
  const rangeDaysCount = useMemo(() => {
    if (!singleOnly && effectiveMode === "range" && value?.from && value?.to) {
      const t1 = new Date(value.from).getTime();
      const t2 = new Date(value.to).getTime();
      return Math.round(Math.abs(t2 - t1) / (1000 * 3600 * 24)) + 1;
    }
    return null;
  }, [singleOnly, effectiveMode, value]);

  const monthNames = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
  ];

  return (
    <div className={styles.datePickerWrapper} ref={wrapperRef}>
      <div className={styles.triggerGroup}>
        {effectiveMode === "single" && (
          <button
            type="button"
            className={styles.stepBtn}
            onClick={(e) => stepSingleDay(-1, e)}
            title="Предыдущий день"
            aria-label="Предыдущий день"
          >
            ‹
          </button>
        )}

        <button
          type="button"
          className={styles.mainTriggerBtn}
          onClick={() => setIsOpen((prev) => !prev)}
          title="Выбрать дату"
          aria-expanded={isOpen}
        >
          <span className={styles.calendarIcon}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
          </span>

          <span className={styles.triggerLabel}>{triggerLabel}</span>

          {rangeDaysCount && (
            <span className={styles.rangeBadge}>{rangeDaysCount} дн</span>
          )}

          <span className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ""}`}>
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </span>
        </button>

        {effectiveMode === "single" && (
          <button
            type="button"
            className={styles.stepBtn}
            onClick={(e) => stepSingleDay(1, e)}
            title="Следующий день"
            aria-label="Следующий день"
          >
            ›
          </button>
        )}
      </div>

      {isOpen && (
        <div className={styles.dropdown} role="dialog" aria-label="Календарь">
          {/* Режимы: День / Период / Все (скрыты в режиме singleOnly) */}
          {!singleOnly && (
            <div className={styles.modeTabs}>
              <button
                type="button"
                className={`${styles.modeTab} ${effectiveMode === "single" ? styles.modeTabActive : ""}`}
                onClick={() => onChange({ mode: "single", date: value?.date || todayStr, from: value?.date || todayStr, to: value?.date || todayStr })}
              >
                1 день
              </button>
              <button
                type="button"
                className={`${styles.modeTab} ${effectiveMode === "range" ? styles.modeTabActive : ""}`}
                onClick={() => {
                  const f = value?.from || value?.date || todayStr;
                  const t = value?.to || shiftDays(f, 6);
                  onChange({ mode: "range", date: f, from: f, to: t });
                }}
              >
                Период
              </button>
              <button
                type="button"
                className={`${styles.modeTab} ${effectiveMode === "all" ? styles.modeTabActive : ""}`}
                onClick={() => selectPreset("all")}
              >
                Все
              </button>
            </div>
          )}

          {/* Быстрые пресеты */}
          <div className={styles.presetsRow}>
            <button type="button" className={styles.presetChip} onClick={() => selectPreset("today")}>Сегодня</button>
            <button type="button" className={styles.presetChip} onClick={() => selectPreset("tomorrow")}>Завтра</button>
            <button type="button" className={styles.presetChip} onClick={() => selectPreset("yesterday")}>Вчера</button>
            {!singleOnly && (
              <>
                <button type="button" className={styles.presetChip} onClick={() => selectPreset("week")}>7 дней</button>
                <button type="button" className={styles.presetChip} onClick={() => selectPreset("month")}>Месяц</button>
                <button type="button" className={styles.presetChip} onClick={() => selectPreset("all")}>Сброс</button>
              </>
            )}
          </div>

          {/* Шапка месяца */}
          <div className={styles.monthHeader}>
            <button type="button" className={styles.monthNavBtn} onClick={prevMonth} title="Предыдущий месяц">‹</button>
            <span className={styles.monthTitle}>{monthNames[viewMonth]} {viewYear}</span>
            <button type="button" className={styles.monthNavBtn} onClick={nextMonth} title="Следующий месяц">›</button>
          </div>

          {/* Дни недели */}
          <div className={styles.weekdaysGrid}>
            <div className={styles.weekdayLabel}>Пн</div>
            <div className={styles.weekdayLabel}>Вт</div>
            <div className={styles.weekdayLabel}>Ср</div>
            <div className={styles.weekdayLabel}>Чт</div>
            <div className={styles.weekdayLabel}>Пт</div>
            <div className={`${styles.weekdayLabel} ${styles.weekendLabel}`}>Сб</div>
            <div className={`${styles.weekdayLabel} ${styles.weekendLabel}`}>Вс</div>
          </div>

          {/* Сетка дат */}
          <div className={styles.daysGrid} onMouseLeave={() => setHoverDate(null)}>
            {calendarDays.map(({ dateStr, dayNum, isCurrentMonth }) => {
              const isToday = dateStr === todayStr;
              const isSingleMode = singleOnly || effectiveMode === "single";
              const isRangeMode = !singleOnly && effectiveMode === "range";

              const isSelected =
                (isSingleMode && (value?.date === dateStr || (!value?.date && dateStr === todayStr))) ||
                (isRangeMode && (value?.from === dateStr || value?.to === dateStr));

              // Проверка на принадлежность диапазону
              let inRange = false;
              let isRangeStart = false;
              let isRangeEnd = false;

              if (isRangeMode) {
                const start = value?.from;
                const end = value?.to || hoverDate;

                if (start && end) {
                  const min = start < end ? start : end;
                  const max = start < end ? end : start;

                  inRange = dateStr > min && dateStr < max;
                  isRangeStart = dateStr === min;
                  isRangeEnd = dateStr === max;
                }
              }

              let cellClasses = styles.dayCell;
              if (!isCurrentMonth) cellClasses += ` ${styles.otherMonthDay}`;
              if (isToday) cellClasses += ` ${styles.todayDay}`;
              if (isSelected) cellClasses += ` ${styles.selectedDay}`;
              if (inRange) cellClasses += ` ${styles.rangeBetween}`;
              if (isRangeStart) cellClasses += ` ${styles.rangeStart}`;
              if (isRangeEnd) cellClasses += ` ${styles.rangeEnd}`;

              const taskCount = dateCounts?.[dateStr] || 0;
              const hasTasks = taskCount > 0;

              return (
                <div key={dateStr} className={cellClasses}>
                  <button
                    type="button"
                    className={styles.dayButton}
                    onClick={() => handleDayClick(dateStr)}
                    onMouseEnter={() => {
                      if (isRangeMode && value?.from && !value?.to) {
                        setHoverDate(dateStr);
                      }
                    }}
                    title={hasTasks ? `${taskCount} заявок` : undefined}
                  >
                    {dayNum}
                    {hasTasks && <span className={styles.hasTasksDot} />}
                  </button>
                </div>
              );
            })}
          </div>

          {/* Футер с кратким резюме */}
          <div className={styles.footer}>
            <div className={styles.footerInfo}>
              {(singleOnly || effectiveMode === "single") && (
                value?.date ? `Выбран день: ${formatHumanMskDate(value.date)}` : `Выбран день: ${formatHumanMskDate(todayStr)}`
              )}
              {!singleOnly && effectiveMode === "range" && (
                value?.from && value?.to
                  ? `${formatHumanMskDate(value.from)} — ${formatHumanMskDate(value.to)} (${rangeDaysCount} дн.)`
                  : value?.from ? `С ${formatHumanMskDate(value.from)} (выберите конец)` : "Выберите период"
              )}
              {!singleOnly && effectiveMode === "all" && "Показаны заявки за все даты"}
            </div>
            <button
              type="button"
              className={styles.footerClearBtn}
              onClick={() => setIsOpen(false)}
            >
              Закрыть
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
