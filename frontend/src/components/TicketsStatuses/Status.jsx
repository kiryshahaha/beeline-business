import styles from "./TicketsStatuses.module.css"

const Status = ({ label, count, variant }) => {
    return (
        <div className={`${styles.statusContainer} ${styles[variant]}`}>
            <span className={styles.status}>{label}</span>
            <span className={styles.count}>({count})</span>
        </div>
    );
};

export default Status;