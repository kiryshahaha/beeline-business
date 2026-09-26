import React from 'react';
import styles from './Menu.module.css';
import Image from 'next/image';
import { useFastStats } from '@/hooks/useFastStats';

export const FastStatsPanel = ({ onClose }) => {
    const { stats, isLoading, isError } = useFastStats();

    return (
        <div className={styles.fastStatsPanel}>
            <div className={styles.brigadesCloseHeader}>
                <div className={styles.dragHandle}>
                    <svg width="12" height="18" viewBox="0 0 12 18" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <circle cx="4" cy="3" r="1.5" fill="currentColor"/>
                        <circle cx="8" cy="3" r="1.5" fill="currentColor"/>
                        <circle cx="4" cy="9" r="1.5" fill="currentColor"/>
                        <circle cx="8" cy="9" r="1.5" fill="currentColor"/>
                        <circle cx="4" cy="15" r="1.5" fill="currentColor"/>
                        <circle cx="8" cy="15" r="1.5" fill="currentColor"/>
                    </svg>
                </div>
                <button className={styles.closeBtn} onClick={onClose}>
                    <Image src="/icons/Frame 33.svg" alt="close" width={16} height={16} />
                </button>
            </div>
            
            <div className={styles.statsContent}>
                {isLoading && <div className={styles.emptyState}>Загрузка...</div>}
                {isError && <div className={styles.emptyState}>Ошибка загрузки статистики</div>}
                {stats && (
                    <div className={styles.statsMonitoringContainer}>
                        <div className={styles.monitoringCard}>
                            <div className={styles.monitoringTitle}>ЗАЯВКИ ПОД УГРОЗОЙ ({stats.at_risk_tickets_count})</div>
                            <div className={styles.monitoringList}>
                                {stats.at_risk_tickets_ids?.length > 0 ? (
                                    stats.at_risk_tickets_ids.map((id) => (
                                        <div key={id} className={styles.monitoringItem}>
                                            <div className={styles.monitoringDot} style={{ backgroundColor: '#FF4444' }} />
                                            <span className={styles.monitoringName}>Заявка #{id}</span>
                                        </div>
                                    ))
                                ) : (
                                    <div className={styles.monitoringItem}>
                                        <div className={styles.monitoringDot} style={{ backgroundColor: '#21CC51' }} />
                                        <span className={styles.monitoringName}>Нет проблемных заявок</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className={styles.monitoringCard}>
                            <div className={styles.monitoringTitle}>СВОБОДНЫЕ ТЕХНИКИ ({stats.idle_workers_count})</div>
                            <div className={styles.monitoringList}>
                                {stats.idle_workers_ids?.length > 0 ? (
                                    stats.idle_workers_ids.map((id) => (
                                        <div key={id} className={styles.monitoringItem}>
                                            <div className={styles.monitoringDot} style={{ backgroundColor: '#0095FF' }} />
                                            <span className={styles.monitoringName}>Техник #{id}</span>
                                        </div>
                                    ))
                                ) : (
                                    <div className={styles.monitoringItem}>
                                        <div className={styles.monitoringDot} style={{ backgroundColor: '#FFC107' }} />
                                        <span className={styles.monitoringName}>Все заняты</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className={styles.brigadesCountBadge}>
                            {stats.active_brigades_count} бригад на смене
                        </div>

                        <div className={styles.slaBadge} style={{ borderColor: stats.sla_compliance_percent >= 90 ? '#21CC51' : '#FF4444' }}>
                            <div className={styles.slaDot} style={{ backgroundColor: stats.sla_compliance_percent >= 90 ? '#21CC51' : '#FF4444' }} />
                            <span style={{ color: stats.sla_compliance_percent >= 90 ? '#21CC51' : '#FF4444', fontFamily: 'monospace', letterSpacing: '1px' }}>
                                SLA {stats.sla_compliance_percent >= 90 ? 'OK' : 'FAIL'} – {stats.average_delay_minutes}M
                            </span>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
