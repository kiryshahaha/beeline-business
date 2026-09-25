"use client"

import React, { useState, useRef } from "react";
import { useClickOutside } from "@/hooks/useClickOutside";
import styles from "./Search.module.css";
import Image from "next/image";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";
import { useBrigades } from "@/hooks/useBrigades";
import { useUsers } from "@/hooks/useUsers";
import { useTickets } from "@/hooks/useTickets";

const ALL_FILTERS = ['бригады', 'работники', 'заявки'];

const Search = () => {
  const [activeFilters, setActiveFilters] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const containerRef = useRef(null);

  const { brigades = [] } = useBrigades();
  const { users = [] } = useUsers();
  const { tickets = [] } = useTickets();

  useClickOutside(containerRef, () => setIsFocused(false));

  const allData = [];
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

  const hasMatches = searchQuery && allData.some(r => r.title.toLowerCase().includes(searchQuery.toLowerCase()));

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
            placeholder="Поиск бригады или задачи..."
            className={styles.input}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onFocus={() => setIsFocused(true)}
          />
        </div>
        <div className={styles.suggestionsWrapper}>
          <div className={styles.suggestions}>
            {allData.map(res => {
              const isMatch = !searchQuery || res.title.toLowerCase().includes(searchQuery.toLowerCase());
              return (
                <div 
                  key={res.id} 
                  className={`${styles.suggestionItem} ${isMatch ? '' : styles.hidden}`}
                >
                  {res.title}
                </div>
              );
            })}
            <div className={`${styles.noResults} ${hasMatches || !searchQuery ? styles.hidden : ''}`}>
              Ничего не найдено
            </div>
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