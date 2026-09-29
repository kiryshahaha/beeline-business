import React from 'react';
import styles from './Menu.module.css';
import Image from 'next/image';
import { useUsers } from '@/hooks/useUsers';
import { useTickets } from '@/hooks/useTickets';

const ROLE_LABELS = {
    foreman: 'Бригадир',
    worker: 'Инженер',
    observer: 'Диспетчер',
    admin: 'Администратор',
};

export const BrigadeDetailsPanel = ({
    brigade,
    selectedWorker,
    onSelectWorker,
    onBack,
    onClose
}) => {
    const { users = [] } = useUsers({ brigade_id: brigade.id });
    const { tickets = [] } = useTickets({ limit: 100 });
    const [searchQuery, setSearchQuery] = React.useState('');

    // Filter users by search query
    const filteredUsers = React.useMemo(() => {
        return users.filter(u => {
            const fullName = `${u.name} ${u.surname}`.toLowerCase();
            return fullName.includes(searchQuery.toLowerCase());
        });
    }, [users, searchQuery]);

    const getInitials = (name, surname) => {
        return `${name?.[0] || ''}${surname?.[0] || ''}`.toUpperCase();
    };

    const formatName = (name, surname) => {
        return `${name || ''} ${surname?.[0] || ''}.`;
    };

    const handleBack = () => {
        onSelectWorker?.(null);
        onBack?.();
    };

    const handleClose = (e) => {
        onSelectWorker?.(null);
        onClose?.(e);
    };

    return (
        <div className={styles.brigadesPanel}>
            <div className={styles.detailsHeader}>
                <button className={styles.backBtn} onClick={handleBack}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M15 18L9 12L15 6" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                </button>
                <div className={styles.detailsTitle}>{brigade.name}</div>
                <button className={styles.closeBtn} onClick={handleClose}>
                    <Image src="/icons/Frame 33.svg" alt="close" width={16} height={16} />
                </button>
            </div>

            <div className={styles.detailsSubheader}>
                {users.length} специалистов
            </div>

            <div className={styles.brigadesContent}>
                {filteredUsers.length === 0 && (
                    <div className={styles.emptyState}>Нет сотрудников</div>
                )}
                {filteredUsers.map(user => {
                    const assignedTickets = tickets.filter(t => t.assigned_worker_id === user.id);
                    const activeTickets = assignedTickets.filter(
                        t => t.status !== "completed" && t.status !== "wont_fix"
                    );
                    const completedTickets = assignedTickets.filter(t => t.status === "completed");
                    const isOnline = user.worker_profile?.is_on_line !== false;
                    const isActive = activeTickets.length > 0;
                    const isSelected = selectedWorker?.id === user.id;

                    const roleLabel = ROLE_LABELS[user.role] || 'Инженер';
                    const maxCapacity = 5;
                    const fillPercent = Math.min(100, Math.round((activeTickets.length / maxCapacity) * 100));

                    return (
                        <div
                            key={user.id}
                            className={`${styles.workerCard} ${isSelected ? styles.activeWorkerCard : ''}`}
                            onClick={() => onSelectWorker?.(isSelected ? null : user)}
                            title={isSelected ? "Кликните, чтобы снять выбор инженера" : "Кликните, чтобы показать только задачи этого инженера"}
                        >
                            <div className={styles.workerCardHeader}>
                                <div className={styles.workerInfo}>
                                    <div className={styles.workerAvatar}>
                                        {getInitials(user.name, user.surname)}
                                    </div>
                                    <div className={styles.workerText}>
                                        <div className={styles.workerName}>{formatName(user.name, user.surname)}</div>
                                        <div className={styles.workerRole}>
                                            {roleLabel}
                                        </div>
                                    </div>
                                </div>
                                <div className={`${styles.workerStatus} ${!isOnline ? styles.statusFree : isActive ? styles.statusActive : styles.statusFree}`}>
                                    {!isOnline ? 'Офлайн' : isActive ? 'В работе' : 'Свободен'}
                                </div>
                            </div>

                            <div className={styles.separator2} />

                            <div className={styles.workerWorkload}>
                                <div className={styles.workloadText}>
                                    <span>Загрузка:</span>
                                    <span>
                                        <b>{activeTickets.length}</b> активных
                                        {completedTickets.length > 0 && ` · ${completedTickets.length} выполнено`}
                                    </span>
                                </div>
                                <div className={styles.workloadBarBg}>
                                    <div
                                        className={styles.workloadBarFill}
                                        style={{
                                            width: `${fillPercent}%`,
                                            background: fillPercent > 80 ? '#FF453A' : fillPercent > 50 ? '#FFC800' : '#30D158',
                                        }}
                                    />
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>

            <div className={styles.brigadesSearchContainer}>
                <div className={styles.brigadesSearch}>
                    <input
                        type="text"
                        placeholder="Поиск сотрудника"
                        className={styles.searchInput}
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                </div>
            </div>
        </div>
    );
};
