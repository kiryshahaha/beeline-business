"use client"

import React, { useState, useRef } from "react";
import { useClickOutside } from "@/hooks/useClickOutside";
import styles from "./Search.module.css";
import Image from "next/image";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";
import { useBrigades } from "@/hooks/useBrigades";
import { useUsers } from "@/hooks/useUsers";
import { useTickets } from "@/hooks/useTickets";

const ALL_FILTERS = ['районы', 'бригады', 'работники', 'заявки'];

const Search = ({
  searchQuery = "",
  onSearchChange,
  onSelectResult,
  onClear,
  districts = [],
}) => {
  const [activeFilters, setActiveFilters] = useState([]);
  const [isFocused, setIsFocused] = useState(false);
  const containerRef = useRef(null);

  const { brigades = [] } = useBrigades();
  const { users = [] } = useUsers();
  const { tickets = [] } = useTickets({ limit: 100 });
  const [unavailableMessage, setUnavailableMessage] = useState("");

  useClickOutside(containerRef, () => setIsFocused(false));

  const allData = [];
  if (activeFilters.length === 0 || activeFilters.includes('районы')) {
    (districts || []).forEach((d) => {
      const parts = [];
      if (d.ticketsCount != null && d.ticketsCount > 0) {
        parts.push(`${d.ticketsCount} заяв.`);
      }
      if (d.office) {
        parts.push(d.office.office_name || "Офис");
      }
      const labelExtra = parts.length > 0 ? ` (${parts.join(" • ")})` : "";
      const short = d.shortName ? ` (${d.shortName})` : "";
      const prefix = d.isOkrug || d.name.toLowerCase().includes("округ") ? "Округ" : "Район";
      allData.push({
        id: `district_${d.name}`,
        title: `${prefix}: ${d.name}${short}${labelExtra}`,
        type: 'district',
        raw: d,
      });
    });
  }
  if (activeFilters.length === 0 || activeFilters.includes('бригады')) {
    (brigades || []).forEach(b => {
      allData.push({ id: `brigade_${b.id}`, title: `Бригада: ${b.name}`, type: 'brigade', raw: b });
    });
  }
  if (activeFilters.length === 0 || activeFilters.includes('работники')) {
    const staff = (users || []).filter(u => u.role === "worker" || u.role === "foreman");
    staff.forEach(u => {
      const fullName = [u.surname, u.name, u.lastname].filter(Boolean).join(" ");
      allData.push({ id: `user_${u.id}`, title: `Сотрудник: ${fullName}`, type: 'user', raw: u });
    });
  }
  if (activeFilters.length === 0 || activeFilters.includes('заявки')) {
    (tickets || []).forEach(t => {
      allData.push({ id: `ticket_${t.id}`, title: `Заявка #${t.id}: ${t.title}`, type: 'ticket', raw: t });
    });
  }

  const matchingData = allData.filter((result) => {
    const q = searchQuery.trim().toLocaleLowerCase("ru");
    if (result.title.toLocaleLowerCase("ru").includes(q)) return true;
    if (result.type === "district") {
      if (result.raw?.shortName && result.raw.shortName.toLocaleLowerCase("ru").includes(q)) return true;
      if (result.raw?.aliases && result.raw.aliases.some(a => a.toLowerCase().includes(q))) return true;
    }
    return false;
  });
  const hasMatches = matchingData.length > 0;

  const showSuggestions = isFocused && searchQuery.length > 0;

  const toggleFilter = (filter) => {
    setActiveFilters(prev => 
      prev.includes(filter) 
        ? prev.filter(f => f !== filter)
        : [...prev, filter]
    );
  };

  const toggleAllFilters = () => {
    if (activeFilters.length === ALL_FILTERS.length) {
      setActiveFilters([]);
    } else {
      setActiveFilters(ALL_FILTERS);
    }
  };

  const selectResult = (result) => {
    const selected = onSelectResult?.(result);
    if (selected === false) {
      setUnavailableMessage("Для этого объекта пока нет доступной точки на карте.");
      return;
    }
    setUnavailableMessage("");
    setIsFocused(false);
  };

  return (
    <div className={styles.container}>
      <div 
        ref={containerRef}
        className={`${styles.searchContainer} ${showSuggestions ? styles.expanded : ''}`}
      >
        <div className={styles.searchHeader}>
          <Image
            src="/icons/icon-search.svg"
            alt="Search icon"
            width={16}
            height={16}
            className={styles.icon}
          />
          <input
            type="text"
            placeholder="Поиск заявки, бригады или сотрудника..."
            className={styles.input}
            value={searchQuery}
            onChange={(e) => {
              onSearchChange?.(e.target.value);
              setUnavailableMessage("");
            }}
            onFocus={() => setIsFocused(true)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setIsFocused(false);
            }}
          />
          {searchQuery && (
            <button
              type="button"
              className={styles.clearButton}
              onClick={(e) => {
                e.stopPropagation();
                onClear?.();
                setUnavailableMessage("");
                setIsFocused(false);
              }}
              title="Очистить поиск"
              aria-label="Очистить поиск"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </svg>
            </button>
          )}
        </div>
        <div className={styles.suggestionsWrapper}>
          <div className={styles.suggestions}>
            {matchingData.slice(0, 12).map((result) => (
              <button
                key={result.id}
                type="button"
                className={styles.suggestionItem}
                onClick={() => selectResult(result)}
              >
                {result.title}
              </button>
            ))}
            <div className={`${styles.noResults} ${hasMatches || !searchQuery ? styles.hidden : ''}`}>
              Ничего не найдено
            </div>
            {unavailableMessage && <div className={styles.noResults}>{unavailableMessage}</div>}
          </div>
        </div>
      </div>
      
      <ExpandableMenu
        renderHeader={({ isOpen }) => (
          <>
            <div className={styles.iconContainer}>
              <Image
                src="/icons/filters.svg"
                alt="Filter icon"
                width={20}
                height={16}
                className={styles.icon}
              />
            </div>
            <span 
              className={`${styles.label} ${isOpen ? styles.labelOpen : ''}`}
              onClick={(e) => {
                e.stopPropagation();
                toggleAllFilters();
              }}
            >
              выбрать все
            </span>
          </>
        )}
      >
        {ALL_FILTERS.map(filter => (
          <button 
            key={filter}
            className={`${styles.filterPill} ${activeFilters.includes(filter) ? styles.active : ''}`}
            onClick={() => toggleFilter(filter)}
          >
            {filter}
          </button>
        ))}
      </ExpandableMenu>
    </div>
  );
};

export default Search;