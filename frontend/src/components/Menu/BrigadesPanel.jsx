import React from 'react';
import styles from './Menu.module.css';
import Image from 'next/image';
import { useBrigades } from '@/hooks/useBrigades';
import { useOffices } from '@/hooks/useOffices';
import { useUsers } from '@/hooks/useUsers';
import { useServiceAreas } from '@/hooks/useServiceAreas';
import { BrigadeDetailsPanel } from './BrigadeDetailsPanel';

export const BrigadesPanel = ({ onClose }) => {
    const { brigades = [] } = useBrigades();
    const { offices = [] } = useOffices();
    const { users = [] } = useUsers({ role: 'worker' });
    const { serviceAreas = [] } = useServiceAreas();

    const [searchQuery, setSearchQuery] = React.useState('');
    const [filterOpen, setFilterOpen] = React.useState(false);
    const [selectedOfficeId, setSelectedOfficeId] = React.useState(null);
    const filterRef = React.useRef(null);
    const [selectedBrigade, setSelectedBrigade] = React.useState(null);

    React.useEffect(() => {
        const handleClickOutside = (e) => {
            if (filterOpen && filterRef.current && !filterRef.current.contains(e.target)) {
                setFilterOpen(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, [filterOpen]);

    const officeMap = React.useMemo(() => {
        const map = {};
        offices.forEach(o => {
            map[o.id] = o;
        });
        return map;
    }, [offices]);

    const serviceAreaMap = React.useMemo(() => {
        const map = {};
        serviceAreas.forEach(sa => {
            map[sa.id] = sa;
        });
        return map;
    }, [serviceAreas]);

    const workerMap = React.useMemo(() => {
        const map = {};
        users.forEach(u => {
            map[u.id] = u;
        });
        return map;
    }, [users]);

    // Apply filters
    const filteredBrigades = React.useMemo(() => {
        return brigades.filter(b => {
            if (selectedOfficeId && b.office_id !== selectedOfficeId) return false;
            if (searchQuery.trim() && !b.name.toLowerCase().includes(searchQuery.toLowerCase())) return false;
            return true;
        });
    }, [brigades, searchQuery, selectedOfficeId]);

    // Grouping by service_area name of the first worker in the brigade
    const grouped = filteredBrigades.reduce((acc, b) => {
        const firstWorkerId = b.worker_ids?.[0];
        const firstWorker = firstWorkerId ? workerMap[firstWorkerId] : null;
        const serviceAreaId = firstWorker?.worker_profile?.service_area_id;
        
        const serviceAreaName = serviceAreaId && serviceAreaMap[serviceAreaId] 
            ? serviceAreaMap[serviceAreaId].name 
            : `Зона Неизвестна`;
            
        if (!acc[serviceAreaName]) acc[serviceAreaName] = [];
        acc[serviceAreaName].push(b);
        return acc;
    }, {});

    const displayGroups = Object.keys(grouped).length > 0 ? grouped : {};

    if (selectedBrigade) {
        return <BrigadeDetailsPanel brigade={selectedBrigade} onBack={() => setSelectedBrigade(null)} onClose={onClose} />;
    }

    return (
        <div className={styles.brigadesPanel}>
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
            
            <div className={styles.brigadesContent}>
                {Object.keys(displayGroups).length === 0 && (
                    <div className={styles.emptyState}>Ничего не найдено</div>
                )}
                {Object.keys(displayGroups).map(district => (
                    <div key={district} className={styles.districtGroup}>
                        <div className={styles.districtTitle}>{district}</div>
                        {displayGroups[district].map(brigade => (
                            <div 
                                key={brigade.id} 
                                className={styles.brigadeCard} 
                                onClick={() => setSelectedBrigade(brigade)}
                                style={{ cursor: 'pointer' }}
                            >
                                <div className={styles.brigadeCardHeader}>
                                    <span className={styles.brigadeName}>{brigade.name}</span>
                                    <div className={`${styles.brigadeBadge} ${brigade.worker_ids?.length >= 10 ? styles.badgeFull : ''}`}>
                                        <span className={styles.badgeHighlight}>{brigade.worker_ids?.length || 0}/10</span> назначены
                                    </div>
                                </div>
                                <div className={styles.separator}></div>
                                <div className={styles.brigadeOffice}>
                                    Офис: {officeMap[brigade.office_id]?.name || brigade.office_id}
                                </div>
                            </div>
                        ))}
                    </div>
                ))}
            </div>

            <div className={styles.brigadesSearchContainer} ref={filterRef}>
                <div className={styles.brigadesSearch}>
                    <input 
                        type="text" 
                        placeholder="Поиск бригады" 
                        className={styles.searchInput}
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                    />
                    <div className={styles.searchDivider} />
                    <button 
                        className={`${styles.filterBtn} ${selectedOfficeId ? styles.filterActiveIcon : ''}`}
                        onClick={() => setFilterOpen(!filterOpen)}
                    >
                        <div 
                            className={styles.filterIconMask} 
                            style={{ WebkitMaskImage: 'url("/icons/filters.svg")', maskImage: 'url("/icons/filters.svg")' }}
                        />
                    </button>
                </div>
                
                {filterOpen && (
                    <div className={styles.filterMenu}>
                        <div className={styles.filterMenuHeader}>Офисы</div>
                        <div 
                            className={`${styles.filterItem} ${selectedOfficeId === null ? styles.active : ''}`}
                            onClick={() => { setSelectedOfficeId(null); setFilterOpen(false); }}
                        >
                            Все офисы
                        </div>
                        {offices.map(o => (
                            <div 
                                key={o.id}
                                className={`${styles.filterItem} ${selectedOfficeId === o.id ? styles.active : ''}`}
                                onClick={() => { setSelectedOfficeId(o.id); setFilterOpen(false); }}
                            >
                                {o.name}
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
};
