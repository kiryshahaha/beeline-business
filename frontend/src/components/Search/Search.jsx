"use client"

import React, { useState, useRef, useEffect } from "react";
import styles from "./Search.module.css";
import Image from "next/image";
import ExpandableMenu from "@/components/ui/ExpandableMenu/ExpandableMenu";

const ALL_FILTERS = ['бригады', 'районы', 'разное'];

const Search = () => {
  const [activeFilters, setActiveFilters] = useState(['бригады']);
  const [searchQuery, setSearchQuery] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setIsFocused(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const mockResults = [
    { id: 1, title: 'Бригада "Альфа"' },
    { id: 2, title: 'Бригада "Бета"' },
    { id: 3, title: 'Задача #1024: Обрыв кабеля' },
    { id: 4, title: 'Задача #1025: Установка роутера' },
  ];

  const hasMatches = searchQuery && mockResults.some(r => r.title.toLowerCase().includes(searchQuery.toLowerCase()));

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
            width={20}
            height={20}
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
            {mockResults.map(res => {
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
        <button 
          className={`${styles.filterPill} ${activeFilters.includes('бригады') ? styles.active : ''}`}
          onClick={() => toggleFilter('бригады')}
        >
          бригады
        </button>
        <button 
          className={`${styles.filterPill} ${activeFilters.includes('районы') ? styles.active : ''}`}
          onClick={() => toggleFilter('районы')}
        >
          районы
        </button>
        <button 
          className={`${styles.filterPill} ${activeFilters.includes('разное') ? styles.active : ''}`}
          onClick={() => toggleFilter('разное')}
        >
          разное
        </button>
      </ExpandableMenu>
    </div>
  );
};

export default Search;