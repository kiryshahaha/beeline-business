"use client";

import React, { useState, useRef } from "react";
import styles from "./DistrictFilter.module.css";
import { useClickOutside } from "@/hooks/useClickOutside";

const MapPinIcon = ({ size = 15 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
    <circle cx="12" cy="10" r="3" />
  </svg>
);

const ChevronDownIcon = ({ size = 13 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

const CloseIcon = ({ size = 12 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.5"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

export default function DistrictFilter({
  districts = [],
  selectedDistrict = null,
  onSelectDistrict,
}) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef(null);

  useClickOutside(containerRef, () => setIsOpen(false));

  const activeDistrictObj = districts.find(
    (d) => d.name.toLowerCase() === (selectedDistrict || "").toLowerCase()
  );

  const handleToggle = () => {
    setIsOpen((prev) => !prev);
  };

  const handleSelect = (districtName) => {
    onSelectDistrict?.(districtName);
    setIsOpen(false);
  };

  const handleClear = (e) => {
    e.stopPropagation();
    onSelectDistrict?.(null);
    setIsOpen(false);
  };

  return (
    <div ref={containerRef} className={styles.container}>
      <button
        type="button"
        className={`${styles.triggerButton} ${selectedDistrict ? styles.active : ""}`}
        onClick={handleToggle}
        title={selectedDistrict ? `Район: ${selectedDistrict}` : "Фильтр по районам"}
      >
        <span className={styles.icon}>
          <MapPinIcon size={14} />
        </span>

        <span className={styles.label}>
          {selectedDistrict
            ? `${selectedDistrict}${activeDistrictObj?.ticketsCount ? ` (${activeDistrictObj.ticketsCount})` : ""}`
            : "Все районы"}
        </span>

        {selectedDistrict ? (
          <span
            className={styles.clearButton}
            onClick={handleClear}
            title="Сбросить фильтр района"
            aria-label="Сбросить фильтр района"
          >
            <CloseIcon size={12} />
          </span>
        ) : (
          <span className={`${styles.arrow} ${isOpen ? styles.open : ""}`}>
            <ChevronDownIcon size={12} />
          </span>
        )}
      </button>

      {isOpen && (
        <div className={styles.dropdown}>
          <button
            type="button"
            className={`${styles.dropdownItem} ${!selectedDistrict ? styles.selected : ""}`}
            onClick={() => handleSelect(null)}
          >
            <div className={styles.itemLeft}>
              <MapPinIcon size={13} />
              <span className={styles.itemName}>Все районы города</span>
            </div>
            <div className={styles.badges}>
              <span className={styles.ticketBadge}>Все</span>
            </div>
          </button>

          {districts.length > 0 && <div className={styles.divider} />}

          {districts.map((district) => {
            const isSelected =
              selectedDistrict &&
              district.name.toLowerCase() === selectedDistrict.toLowerCase();

            return (
              <button
                key={district.name}
                type="button"
                className={`${styles.dropdownItem} ${isSelected ? styles.selected : ""}`}
                onClick={() => handleSelect(district.name)}
              >
                <div className={styles.itemLeft}>
                  <MapPinIcon size={13} />
                  <span className={styles.itemName}>
                    {district.name}
                    {district.shortName ? ` (${district.shortName})` : ""}
                  </span>
                </div>
                <div className={styles.badges}>
                  {district.isOkrug && <span className={styles.okrugBadge}>АО</span>}
                  {district.office && (
                    <span className={styles.officeBadge} title="Есть офис обслуживания">
                      Офис
                    </span>
                  )}
                  {district.ticketsCount != null && (
                    <span className={styles.ticketBadge}>
                      {district.ticketsCount}
                    </span>
                  )}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
