import styles from "./Notifications.module.css"
import Image from "next/image"
import { useNotificationsWS } from "@/hooks/useNotificationsWS"

const Notifications = () => {
    const { hasUnread, clearUnread } = useNotificationsWS();

    return (
        <div className={styles.container} onClick={clearUnread}>
            <Image src="/icons/bell.svg" alt="Уведомления" width={18} height={18} />
            {hasUnread && <div className={styles.unreadBadge} />}
        </div>
    );
};

export default Notifications;