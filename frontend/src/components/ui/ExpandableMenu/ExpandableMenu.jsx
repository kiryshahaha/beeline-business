"use client";

import React, { useState, useEffect, useRef } from "react";
import styles from "./ExpandableMenu.module.css";

export default function ExpandableMenu({
  renderHeader,
  header,
  children,
  baseSize = 36,
  className = "",
  direction = "down",
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

  const isUp = direction === "up";

  return (
    <div
      ref={menuRef}
      data-open={isOpen ? "true" : undefined}
      data-direction={direction}
      className={`${styles.container} ${isOpen ? styles.open : ""} ${isOpen ? "open" : ""} ${isUp ? styles.directionUp : ""} ${className}`}
      style={{
        "--base-size": `${baseSize}px`,
      }}
    >
      <div className={styles.header} onClick={() => setIsOpen(!isOpen)}>
        {renderHeader ? renderHeader({ isOpen, setIsOpen }) : header}
      </div>
      <div className={styles.bodyWrapper}>
        <div className={styles.body}>
          <div className={styles.bodyContent}>{children}</div>
        </div>
      </div>
    </div>
  );
}
