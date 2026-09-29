"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";
import { useAuth } from "@/providers/AuthProvider";
import { searchAddressSuggestions, reverseGeocodeCoordinates } from "@/utils/geocoding";
import styles from "./CreateTicketModal.module.css";

function parseJwt(token) {
  if (!token) return null;
  try {
    const base64Url = token.split(".")[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}

function formatApiError(errData, fallbackMessage) {
  if (!errData) return fallbackMessage;
  if (typeof errData.detail === "string") return errData.detail;
  if (Array.isArray(errData.detail)) {
    return errData.detail
      .map((item) => {
        const field = item.loc ? item.loc[item.loc.length - 1] : "";
        return `${field ? field + ": " : ""}${item.msg}`;
      })
      .join("; ");
  }
  if (errData.message) return errData.message;
  return fallbackMessage;
}

async function getObserverToken(currentToken) {
  if (currentToken) {
    const payload = parseJwt(currentToken);
    const isExpired = payload?.exp && payload.exp * 1000 < Date.now() + 15000;
    if (!isExpired && payload?.role === "observer") {
      return currentToken;
    }
  }

  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        username: "demo_observer",
        password: "ObserverSecret123!",
      }),
    });
    if (res.ok) {
      const data = await res.json();
      return data.access_token;
    }
  } catch (err) {
    console.warn("Failed to get observer token automatically:", err);
  }
  return currentToken;
}

const WORK_TYPES = [
  { id: 1, name: "Подключение клиентов Базовая", category: "connection", priority: 2, defaultMinutes: 60 },
  { id: 2, name: "Авария на ТКД", category: "emergency", priority: 1, defaultMinutes: 90 },
  { id: 4, name: "Локальная заявка / ремонт у клиента", category: "repair", priority: 3, defaultMinutes: 60 },
  { id: 3, name: "Дозаказ оборудования", category: "additional", priority: 3, defaultMinutes: 45 },
];

export default function CreateTicketModal({
  isOpen,
  onClose,
  initialCoordinates = null,
  onStartPickOnMap,
  onTicketCreated,
}) {
  const queryClient = useQueryClient();
  const { token, login } = useAuth();
  const tokenPayload = useMemo(() => parseJwt(token), [token]);
  const userRole = tokenPayload?.role;
  const isObserver = !userRole || userRole === "observer";

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [workTypeId, setWorkTypeId] = useState(1);

  // Адресные поля
  const [addressSearchQuery, setAddressSearchQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [isSearchingAddress, setIsSearchingAddress] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchTimeoutRef = useRef(null);

  const [city, setCity] = useState("Москва");
  const [district, setDistrict] = useState("Тверской");
  const [street, setStreet] = useState("");
  const [buildingNumber, setBuildingNumber] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [formattedAddress, setFormattedAddress] = useState("");
  const [showManualAddress, setShowManualAddress] = useState(false);

  // Временные параметры
  const [visitStart, setVisitStart] = useState("");
  const [visitEnd, setVisitEnd] = useState("");
  const [durationMinutes, setDurationMinutes] = useState(60);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  // Автоматический реверс-геокодинг при передаче координат клика с карты
  useEffect(() => {
    if (!isOpen) return;

    if (initialCoordinates) {
      const lat = parseFloat(initialCoordinates.lat || initialCoordinates[1]);
      const lng = parseFloat(initialCoordinates.lng || initialCoordinates[0]);
      queueMicrotask(() => {
        setLatitude(lat.toFixed(5));
        setLongitude(lng.toFixed(5));
      });

      // Запускаем распознавание адреса по координатам точки на карте
      reverseGeocodeCoordinates(lat, lng).then((parsed) => {
        if (parsed) {
          setCity(parsed.city || "Москва");
          setDistrict(parsed.district || "Центральный");
          setStreet(parsed.street || "");
          setBuildingNumber(parsed.buildingNumber || "1");
          setFormattedAddress(parsed.formattedAddress);
          setAddressSearchQuery(parsed.formattedAddress);
        }
      });
    } else if (!latitude) {
      queueMicrotask(() => {
        // Центр Москвы по умолчанию
        setLatitude("55.7558");
        setLongitude("37.6173");
        setStreet("Тверская");
        setBuildingNumber("1");
        setDistrict("Тверской");
        setFormattedAddress("Москва, Тверская, 1");
        setAddressSearchQuery("Москва, Тверская, 1");
      });
    }

    // Временные окна визита (сегодня с 10:00 до 14:00)
    const now = new Date();
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 10, 0);
    const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 14, 0);

    const formatForInput = (d) => {
      const year = d.getFullYear();
      const month = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      const hours = String(d.getHours()).padStart(2, "0");
      const mins = String(d.getMinutes()).padStart(2, "0");
      return `${year}-${month}-${day}T${hours}:${mins}`;
    };

    queueMicrotask(() => {
      setVisitStart(formatForInput(start));
      setVisitEnd(formatForInput(end));
      setErrorMessage(null);
    });
  }, [isOpen, initialCoordinates, latitude]);

  // Обработка живого поиска адреса с автокомплитом
  const handleAddressInputChange = (e) => {
    const val = e.target.value;
    setAddressSearchQuery(val);
    setShowSuggestions(true);

    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);

    if (val.trim().length < 2) {
      setSuggestions([]);
      return;
    }

    setIsSearchingAddress(true);
    searchTimeoutRef.current = setTimeout(async () => {
      const results = await searchAddressSuggestions(val);
      setSuggestions(results);
      setIsSearchingAddress(false);
    }, 280);
  };

  const handleSelectSuggestion = (suggestion) => {
    const parsed = suggestion.parsed;
    if (parsed) {
      setCity(parsed.city || "Москва");
      setDistrict(parsed.district || "Тверской");
      setStreet(parsed.street || "");
      setBuildingNumber(parsed.buildingNumber || "1");
      setLatitude(Number(parsed.lat).toFixed(5));
      setLongitude(Number(parsed.lng).toFixed(5));
      setFormattedAddress(parsed.formattedAddress);
      setAddressSearchQuery(parsed.formattedAddress);
    }
    setShowSuggestions(false);
  };

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!title.trim()) {
      setErrorMessage("Укажите название заявки");
      return;
    }

    let effectiveStreet = street.trim();
    let effectiveBuilding = buildingNumber.trim();
    const query = addressSearchQuery.trim();

    if (!effectiveStreet && query) {
      const match = query.match(/(?:д(?:ом|\.)?\s*)?(\d+[\wа-яА-Я/-]*)$/i);
      if (match) {
        effectiveBuilding = match[1];
        effectiveStreet = query.slice(0, match.index).replace(/,\s*$/, "").trim();
      } else {
        effectiveStreet = query;
      }
    }
    if (!effectiveStreet) effectiveStreet = "Тверская";
    if (!effectiveBuilding) effectiveBuilding = "1";

    const startDate = new Date(visitStart);
    let endDate = new Date(visitEnd);
    if (isNaN(startDate.getTime())) {
      setErrorMessage("Укажите корректное время начала визита");
      return;
    }
    if (isNaN(endDate.getTime()) || endDate <= startDate) {
      endDate = new Date(startDate.getTime() + 4 * 60 * 60 * 1000);
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      // Получаем валидный observer токен (при необходимости прозрачно авторизуется как demo_observer)
      const observerToken = await getObserverToken(token);
      const authHeader = observerToken ? { Authorization: `Bearer ${observerToken}` } : {};

      // 1. Создаем или получаем локацию в БД
      let locationId = null;
      try {
        const cleanDist = (district.trim() || "Тверской")
          .replace(/\s*(район|муниципальный округ|административный округ)\s*/gi, "")
          .trim() || "Тверской";

        const locRes = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/location`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeader,
          },
          credentials: "include",
          body: JSON.stringify({
            city: city.trim() || "Москва",
            district: cleanDist,
            street: effectiveStreet,
            building_number: effectiveBuilding,
            latitude: parseFloat(latitude) || 55.7558,
            longitude: parseFloat(longitude) || 37.6173,
          }),
        });

        if (locRes.ok) {
          const locData = await locRes.json();
          locationId = locData.id;
        } else {
          const locErr = await locRes.json().catch(() => ({}));
          console.warn("POST /location returned error, trying fallback:", locErr);
        }
      } catch (locErr) {
        console.warn("Location network error:", locErr);
      }

      // Резервный поиск существующей локации в БД
      if (!locationId) {
        try {
          const fallbackRes = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/location/1`, {
            headers: authHeader,
            credentials: "include",
          });
          if (fallbackRes.ok) {
            const fbData = await fallbackRes.json();
            locationId = fbData.id;
          }
        } catch {}
        if (!locationId) locationId = 1;
      }

      // 2. Создаем заявку
      const selectedWorkType = WORK_TYPES.find((w) => w.id === Number(workTypeId)) || WORK_TYPES[0];
      const ticketPayload = {
        location_id: Number(locationId),
        title: title.trim(),
        description: description.trim() || null,
        work_type_id: Number(selectedWorkType.id),
        category: selectedWorkType.category,
        priority: Number(selectedWorkType.priority),
        estimated_duration_minutes: Math.max(15, Number(durationMinutes) || 60),
        visit_window_start: startDate.toISOString(),
        visit_window_end: endDate.toISOString(),
      };

      const ticketRes = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/tickets`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeader,
        },
        credentials: "include",
        body: JSON.stringify(ticketPayload),
      });

      if (!ticketRes.ok) {
        const ticketErr = await ticketRes.json().catch(() => ({}));
        throw new Error(formatApiError(ticketErr, "Не удалось создать заявку"));
      }

      const createdTicket = await ticketRes.json();

      // Инвалидируем кэш для немедленного обновления карты и списков
      queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
      queryClient.invalidateQueries({ queryKey: ["tickets"] });
      queryClient.invalidateQueries({ queryKey: ["fast-stats"] });
      queryClient.invalidateQueries({ queryKey: ["tickets-summary"] });
      queryClient.invalidateQueries({ queryKey: ["locations"] });

      if (onTicketCreated) {
        onTicketCreated(createdTicket);
      }
      onClose();
    } catch (err) {
      setErrorMessage(err.message || "Ошибка при создании заявки");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <div className={styles.titleGroup}>
            <h2 className={styles.title}>Новая заявка</h2>
            <p className={styles.subtitle}>Создание инцидента или подключения на карте</p>
          </div>
          <button type="button" className={styles.closeBtn} onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className={styles.body}>
          {!isObserver && (
            <div className={styles.roleWarningBanner}>
              <div className={styles.roleWarningText}>
                Создание заявок доступно диспетчеру (роль: observer). Сейчас выполнен вход под ролью «{userRole}».
              </div>
              <button
                type="button"
                className={styles.switchRoleBtn}
                onClick={async () => {
                  try {
                    const res = await fetch(`${process.env.NEXT_PUBLIC_ENDPOINT}/auth/login`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      credentials: "include",
                      body: JSON.stringify({ username: "demo_observer", password: "ObserverSecret123!" }),
                    });
                    if (res.ok) {
                      const data = await res.json();
                      login(data.access_token);
                      setErrorMessage(null);
                    }
                  } catch {
                    setErrorMessage("Не удалось переключиться на demo_observer");
                  }
                }}
              >
                Войти как demo_observer
              </button>
            </div>
          )}

          {errorMessage && <div className={styles.errorBanner}>{errorMessage}</div>}

          {/* Название заявки */}
          <div className={styles.formGroup}>
            <label className={styles.label}>Название заявки *</label>
            <input
              type="text"
              className={styles.input}
              placeholder="Например: Подключение B2B клиента или Авария оптики"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>

          {/* Блок выбора места выполнения: Поиск по адресу ИЛИ Клик на карте */}
          <div className={styles.locationSection}>
            <div className={styles.locationHeader}>
              <span className={styles.locationTitle}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFC800" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                  <circle cx="12" cy="10" r="3"></circle>
                </svg>
                Место выполнения работ *
              </span>

              {onStartPickOnMap && (
                <button
                  type="button"
                  className={styles.pickOnMapBtn}
                  onClick={() => {
                    onClose();
                    onStartPickOnMap();
                  }}
                  title="Кликнуть в любом месте на карте, чтобы поставить заявку"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="22" y1="12" x2="18" y2="12"></line>
                    <line x1="6" y1="12" x2="2" y2="12"></line>
                    <line x1="12" y1="6" x2="12" y2="2"></line>
                    <line x1="12" y1="22" x2="12" y2="18"></line>
                  </svg>
                  <span>Указать на карте</span>
                </button>
              )}
            </div>

            {/* Поисковая строка с автокомплитом адреса */}
            <div className={styles.searchWrapper}>
              <div className={styles.searchIconWrapper}>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="8"></circle>
                  <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
              </div>
              <input
                type="text"
                className={styles.searchInput}
                placeholder="Поиск адреса (улица, дом, метро)..."
                value={addressSearchQuery}
                onChange={handleAddressInputChange}
                onFocus={() => {
                  if (suggestions.length > 0) setShowSuggestions(true);
                }}
              />
              {addressSearchQuery && (
                <button
                  type="button"
                  className={styles.clearSearchBtn}
                  onClick={() => {
                    setAddressSearchQuery("");
                    setSuggestions([]);
                    setShowSuggestions(false);
                  }}
                >
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                  </svg>
                </button>
              )}

              {/* Выпадающий список найденных адресов */}
              {showSuggestions && suggestions.length > 0 && (
                <div className={styles.suggestionsList}>
                  {suggestions.map((s) => (
                    <div
                      key={s.id}
                      className={styles.suggestionItem}
                      onClick={() => handleSelectSuggestion(s)}
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#FFC800" strokeWidth="2" style={{ flexShrink: 0 }}>
                        <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
                        <circle cx="12" cy="10" r="3"></circle>
                      </svg>
                      <span>{s.label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Карточка выбранного адреса */}
            {street && (
              <div className={styles.resolvedCard}>
                <div className={styles.resolvedText}>
                  <span>{street}{buildingNumber ? `, д. ${buildingNumber}` : ""}</span>
                  {district && <span style={{ opacity: 0.65 }}>({district})</span>}
                </div>
                <div className={styles.resolvedCoords}>
                  {latitude && longitude ? `${latitude}, ${longitude}` : ""}
                </div>
              </div>
            )}

            {/* Переключатель ручной правки адреса */}
            <div>
              <button
                type="button"
                style={{
                  background: "transparent",
                  border: "none",
                  color: "rgba(255, 200, 0, 0.8)",
                  fontSize: "11px",
                  cursor: "pointer",
                  padding: "0",
                  textDecoration: "underline",
                }}
                onClick={() => setShowManualAddress(!showManualAddress)}
              >
                {showManualAddress ? "Скрыть ручные поля" : "Уточнить улицу / дом / район вручную"}
              </button>
            </div>

            {showManualAddress && (
              <div className={styles.row3} style={{ marginTop: "4px" }}>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Улица</label>
                  <input
                    type="text"
                    className={styles.input}
                    value={street}
                    onChange={(e) => setStreet(e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Дом</label>
                  <input
                    type="text"
                    className={styles.input}
                    value={buildingNumber}
                    onChange={(e) => setBuildingNumber(e.target.value)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Район</label>
                  <input
                    type="text"
                    className={styles.input}
                    value={district}
                    onChange={(e) => setDistrict(e.target.value)}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Вид работ и норматив */}
          <div className={styles.row2}>
            <div className={styles.formGroup}>
              <label className={styles.label}>Вид работ</label>
              <select
                className={styles.select}
                value={workTypeId}
                onChange={(e) => {
                  const id = Number(e.target.value);
                  setWorkTypeId(id);
                  const wt = WORK_TYPES.find((w) => w.id === id);
                  if (wt) setDurationMinutes(wt.defaultMinutes);
                }}
              >
                {WORK_TYPES.map((wt) => (
                  <option key={wt.id} value={wt.id}>
                    {wt.name}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles.formGroup}>
              <label className={styles.label}>Норматив времени (мин)</label>
              <input
                type="number"
                min="15"
                max="480"
                step="5"
                className={styles.input}
                value={durationMinutes}
                onChange={(e) => setDurationMinutes(e.target.value)}
              />
            </div>
          </div>

          {/* Окно визита */}
          <div className={styles.row2}>
            <div className={styles.formGroup}>
              <label className={styles.label}>Окно визита С</label>
              <input
                type="datetime-local"
                className={styles.input}
                value={visitStart}
                onChange={(e) => setVisitStart(e.target.value)}
                required
              />
            </div>

            <div className={styles.formGroup}>
              <label className={styles.label}>Окно визита По</label>
              <input
                type="datetime-local"
                className={styles.input}
                value={visitEnd}
                onChange={(e) => setVisitEnd(e.target.value)}
                required
              />
            </div>
          </div>

          {/* Примечание */}
          <div className={styles.formGroup}>
            <label className={styles.label}>Примечание (необязательно)</label>
            <textarea
              className={styles.textarea}
              rows={2}
              placeholder="Комментарий для инженера..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          {errorMessage && (
            <div className={styles.errorBanner}>
              {errorMessage}
            </div>
          )}

          <div className={styles.footer}>
            <button type="button" className={styles.cancelBtn} onClick={onClose} disabled={isSubmitting}>
              Отмена
            </button>
            <button type="submit" className={styles.submitBtn} disabled={isSubmitting}>
              {isSubmitting ? "Создание..." : "Создать заявку"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
