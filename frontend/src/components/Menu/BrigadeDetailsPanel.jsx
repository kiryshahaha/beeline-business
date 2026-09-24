import React from 'react';
import styles from './Menu.module.css';
import Image from 'next/image';
import { useUsers } from '@/hooks/useUsers';

export const BrigadeDetailsPanel = ({ brigade, onBack, onClose }) => {
    const { users = [] } = useUsers({ brigade_id: brigade.id });
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

    return (
        <div className={styles.brigadesPanel}>
            <div className={styles.detailsHeader}>
                <button className={styles.backBtn} onClick={onBack}>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M15 18L9 12L15 6" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                </button>
                <div className={styles.detailsTitle}>{brigade.name}</div>
                <button className={styles.closeBtn} onClick={onClose}>
                    <Image src="/icons/Frame 33.svg" alt="close" width={16} height={16} />
                </button>
            </div>

            <div className={styles.detailsSubheader}>
                {users.length} сотрудников
            </div>

            <div className={styles.brigadesContent}>
                {filteredUsers.length === 0 && (
                    <div className={styles.emptyState}>Нет сотрудников</div>
                )}
                {filteredUsers.map(user => {
                    // Mocking workload for now, as we don't have this in UserRead
                    const currentTasks = user.id % 6; // random looking number 0-5
                    const maxTasks = 5;
                    const isActive = currentTasks > 0;

                    return (
                        <div key={user.id} className={styles.workerCard}>
                            <div className={styles.workerCardHeader}>
                                <div className={styles.workerInfo}>
                                    <div className={styles.workerAvatar}>
                                        {getInitials(user.name, user.surname)}
                                    </div>
                                    <div className={styles.workerText}>
                                        <div className={styles.workerName}>{formatName(user.name, user.surname)}</div>
                                        <div className={styles.workerRole}>
                                            {user.role === 'foreman' ? 'Бригадир' : 'Старший техник'}
                                        </div>
                                    </div>
                                </div>
                                <div className={`${styles.workerStatus} ${isActive ? styles.statusActive : styles.statusFree}`}>
                                    {isActive ? 'Активен' : 'Свободен'}
                                </div>
                            </div>

                            <div className={styles.separator2} />

                            <div className={styles.workerWorkload}>
                                <div className={styles.workloadText}>
                                    <span>Загрузка:</span>
                                    <span><b>{currentTasks}/{maxTasks}</b> задач</span>
                                </div>
                                <div className={styles.workloadBarBg}>
                                    <div
                                        className={styles.workloadBarFill}
                                        style={{ width: `${(currentTasks / maxTasks) * 100}%` }}
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
                    <div className={styles.searchDivider} />
                    <button className={styles.filterBtn}>
                        <div
                            className={styles.filterIconMask}
                            style={{ WebkitMaskImage: 'url("/icons/filters.svg")', maskImage: 'url("/icons/filters.svg")' }}
                        />
                    </button>
                </div>
            </div>
        </div>
    );
};
