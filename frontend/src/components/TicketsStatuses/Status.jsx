import React from "react";
import styles from "./TicketsStatuses.module.css";

const Status = ({ label, count, variant, onClick, isInactive = false, isInteractive = true }) => {
    return (
        <div 
            className={`
                ${styles.statusContainer} 
                ${styles[variant] || ""} 
                ${isInteractive ? styles.interactive : ""} 
                ${isInactive ? styles.inactive : ""}
            `}
            onClick={(e) => {
                if (onClick) {
                    e.stopPropagation();
                    onClick();
                }
            }}
        >
            <span className={styles.status}>{label}</span>
            <span className={styles.count}>({count})</span>
        </div>
    );
};

export default Status;