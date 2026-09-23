import styles from "./TicketsStatuses.module.css"

const Status = ({ label, count, variant, onClick, isInteractive, isInactive }) => {
    return (
        <div 
            className={`
                ${styles.statusContainer} 
                ${styles[variant]} 
                ${isInteractive ? styles.interactive : ""} 
                ${isInactive ? styles.inactive : ""}
            `}
            onClick={(e) => {
                if (onClick && isInteractive) {
                    e.stopPropagation(); // Чтобы клик по таблетке не закрывал/открывал общую плашку
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