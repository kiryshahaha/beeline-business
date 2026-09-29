"use client";

import React, { useState, useEffect, useRef, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/apiFetch";
import { useAuth } from "@/providers/AuthProvider";
import { searchAddressSuggestions, reverseGeocodeCoordinates } from "@/utils/geocoding";
import { useWorkTypes } from "@/hooks/useWorkTypes";
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

  const { workTypes = [] } = useWorkTypes();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [workTypeId, setWorkTypeId] = useState(null);

  const effectiveWorkTypeId = workTypeId ?? (workTypes[0]?.id ?? null);
  const selectedWorkType = useMemo(() => {
    if (!effectiveWorkTypeId || !workTypes.length) return null;
    return workTypes.find((w) => w.id === Number(effectiveWorkTypeId)) || workTypes[0] || null;
  }, [workTypes, effectiveWorkTypeId]);

  // Адресные поля
  const [addressSearchQuery, setAddressSearchQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [isSearchingAddress, setIsSearchingAddress] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const searchTimeoutRef = useRef(null);

  const [city, setCity] = useState("Москва");
  const [district, setDistrict] = useState("");
  const [street, setStreet] = useState("");
  const [buildingNumber, setBuildingNumber] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [formattedAddress, setFormattedAddress] = useState("");
  const [showManualAddress, setShowManualAddress] = useState(false);

  // Временные параметры
  const [visitStart, setVisitStart] = useState("");
  const [visitEnd, setVisitEnd] = useState("");
  const [customDurationMinutes, setCustomDurationMinutes] = useState(null);
  const durationMinutes =
    customDurationMinutes ??
    (selectedWorkType?.norm_minutes || selectedWorkType?.work_minutes || 60);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  // Автоматический реверс-геокодинг при передаче координат клика с карты
  useEffect(() => {
    if (!isOpen) return;

    if (initialCoordinates) {
      const lat = parseFloat(initialCoordinates.lat || initialCoordinates[1]);
      const lng = parseFloat(initialCoordinates.lng || initialCoordinates[0]);
      if (!isNaN(lat) && !isNaN(lng)) {
        queueMicrotask(() => {
          setLatitude(lat.toFixed(5));
          setLongitude(lng.toFixed(5));
        });

        // Запускаем распознавание адреса по координатам точки на карте
        reverseGeocodeCoordinates(lat, lng).then((parsed) => {
          if (parsed) {
            setCity(parsed.city || "Москва");
            setDistrict(parsed.district || "");
            setStreet(parsed.street || "");
            setBuildingNumber(parsed.buildingNumber || "");
            setFormattedAddress(parsed.formattedAddress || "");
            setAddressSearchQuery(parsed.formattedAddress || "");
          }
        });
      }
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
  }, [isOpen, initialCoordinates]);

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
      setDistrict(parsed.district || "");
      setStreet(parsed.street || "");
      setBuildingNumber(parsed.buildingNumber || "");
      if (parsed.lat != null && parsed.lng != null) {
        setLatitude(Number(parsed.lat).toFixed(5));
        setLongitude(Number(parsed.lng).toFixed(5));
      }
      setFormattedAddress(parsed.formattedAddress || "");
      setAddressSearchQuery(parsed.formattedAddress || "");
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
    if (!selectedWorkType) {
      setErrorMessage("Выберите вид работ");
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

    if (!effectiveStreet) {
      setErrorMessage("Укажите улицу или выберите адрес из списка подсказок");
      return;
    }
    if (!effectiveBuilding) {
      setErrorMessage("Укажите номер дома");
      return;
    }

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
      // 1. Создаем или получаем локацию в БД
      let finalLat = parseFloat(latitude);
      let finalLng = parseFloat(longitude);

      // Если координаты не выбраны вручную/с карты, пробуем быстро геокодировать строку адреса
      if ((isNaN(finalLat) || isNaN(finalLng)) && query) {
        try {
          const found = await searchAddressSuggestions(query);
          if (found && found.length > 0 && found[0].parsed?.lat && found[0].parsed?.lng) {
            finalLat = parseFloat(found[0].parsed.lat);
            finalLng = parseFloat(found[0].parsed.lng);
            if (!district && found[0].parsed.district) {
              setDistrict(found[0].parsed.district);
            }
          }
        } catch {}
      }

      const cleanDist = (district.trim() || "")
        .replace(/\s*(район|муниципальный округ|административный округ)\s*/gi, "")
        .trim();

      const locPayload = {
        city: city.trim() || "Москва",
        district: cleanDist || "Центральный",
        street: effectiveStreet,
        building_number: effectiveBuilding,
      };
      if (!isNaN(finalLat) && !isNaN(finalLng)) {
        locPayload.latitude = finalLat;
        locPayload.longitude = finalLng;
      }

      const locRes = await apiFetch("/location", {
        method: "POST",
        body: JSON.stringify(locPayload),
      });

      if (!locRes.ok) {
        const locErr = await locRes.json().catch(() => ({}));
        throw new Error(formatApiError(locErr, "Не удалось сохранить адрес заявки"));
      }

      const locData = await locRes.json();
      const locationId = locData.id;
      const serviceAreaId = locData.service_area_id;

      if (!locationId) {
        throw new Error("Сервер не вернул идентификатор созданного адреса");
      }

      // 2. Создаем заявку с динамическими параметрами
      const ticketWorkTypeId = selectedWorkType.id;
      const ticketPayload = {
        location_id: Number(locationId),
        title: title.trim(),
        description: description.trim() || null,
        work_type_id: Number(ticketWorkTypeId),
        estimated_duration_minutes: Math.max(15, Number(durationMinutes) || selectedWorkType.norm_minutes || 60),
        visit_window_start: startDate.toISOString(),
        visit_window_end: endDate.toISOString(),
      };
      if (serviceAreaId) {
        ticketPayload.service_area_id = Number(serviceAreaId);
      }
      if (selectedWorkType.category) {
        ticketPayload.category = selectedWorkType.category;
      }
      if (selectedWorkType.default_priority || selectedWorkType.priority) {
        ticketPayload.priority = Number(selectedWorkType.default_priority || selectedWorkType.priority);
      }

      const ticketRes = await apiFetch("/tickets", {
        method: "POST",
        body: JSON.stringify(ticketPayload),
      });

      if (!ticketRes.ok) {
        const ticketErr = await ticketRes.json().catch(() => ({}));
        throw new Error(formatApiError(ticketErr, "Не удалось создать заявку"));
      }

      const createdTicket = await ticketRes.json();

      // 3. Автоматически резервируем обязательное оборудование из правил вида работ (planning-rules)
      try {
        const rulesRes = await apiFetch(`/work-types/${ticketWorkTypeId}/planning-rules`);
        if (rulesRes.ok) {
          const rulesData = await rulesRes.json();
          const reqAppliances = rulesData?.required_appliances || [];
          for (const req of reqAppliances) {
            if (req.appliance_id && req.quantity > 0) {
              await apiFetch(`/tickets/${createdTicket.id}/appliances`, {
                method: "POST",
                body: JSON.stringify({
                  appliance_id: req.appliance_id,
                  quantity: req.quantity,
                }),
              }).catch((e) => console.warn("Could not auto-reserve appliance:", e));
            }
          }
        }
      } catch (appErr) {
        console.warn("Failed to fetch planning rules for appliances:", appErr);
      }

      // Инвалидируем кэш для немедленного обновления карты и списков (FE-04)
      queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
      queryClient.invalidateQueries({ queryKey: ["fastStats"] });
      queryClient.invalidateQueries({ queryKey: ["ticketsSummary"] });
      queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
      queryClient.invalidateQueries({ queryKey: ["location"] });

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
                Создание заявок доступно только диспетчерам и администраторам системы. Сейчас выполнен вход под ролью «{userRole}».
              </div>
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
                value={effectiveWorkTypeId || ""}
                onChange={(e) => {
                  const id = Number(e.target.value);
                  setWorkTypeId(id);
                  setCustomDurationMinutes(null);
                }}
                disabled={workTypes.length === 0}
              >
                {workTypes.length === 0 ? (
                  <option value="">Загрузка видов работ...</option>
                ) : (
                  workTypes.map((wt) => (
                    <option key={wt.id} value={wt.id}>
                      {wt.name} ({wt.norm_minutes || wt.work_minutes || 60} мин)
                    </option>
                  ))
                )}
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
                onChange={(e) => setCustomDurationMinutes(e.target.value)}
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
            <button type="submit" className={styles.submitBtn} disabled={isSubmitting || workTypes.length === 0}>
              {isSubmitting ? "Создание..." : "Создать заявку"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
