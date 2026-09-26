"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/AuthProvider";
import styles from "./settings.module.css";

const Settings = () => {
    const { logout } = useAuth();
    const router = useRouter();

    const handleLogout = async () => {
        await logout();
        router.push("/login");
    };

    return (
        <div className={styles.page}>
            <button id="logout-btn" className={styles.logoutBtn} onClick={handleLogout}>
                Выйти из системы
            </button>
        </div>
    );
};

export default Settings;