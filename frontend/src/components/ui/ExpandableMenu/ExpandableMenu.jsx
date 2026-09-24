"use client"

import React, { useState, useEffect, useRef } from "react";
import styles from "./ExpandableMenu.module.css";

export default function ExpandableMenu({
  renderHeader,
  header,
  children,
  baseSize = 36,
  className = ""
}) {
  const [isOpen, setIsOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  return (
    <div
      ref={menuRef}
      className={`${styles.container} ${isOpen ? styles.open : ""} ${className}`}
      style={{
        "--base-size": `${baseSize}px`,
      }}
    >
      <div 
        className={styles.header} 
        onClick={() => setIsOpen(!isOpen)}
      >
        {renderHeader ? renderHeader({ isOpen }) : header}
      </div>
      <div className={styles.bodyWrapper}>
        <div className={styles.body}>
          <div className={styles.bodyContent}>
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
