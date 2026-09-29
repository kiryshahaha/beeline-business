import Image from "next/image";
import styles from "./SmallStatsCard.module.css";

const SmallStatsCard = ({ 
    header, 
    num, 
    trend, 
    trendType = "neutral", 
    svg, 
    footer, 
    loading = false,
    svgClassName,
    svgStyle
}) => {
    const pillClass = 
        trendType === 'positive' ? styles.pillPositive : 
        trendType === 'negative' ? styles.pillNegative : 
        styles.pillNeutral;

    const isUp = trend && trend.includes('+');
    const isDown = trend && trend.includes('-');
    const trendIconPath = isUp ? '/icons/trending-up.svg' : isDown ? '/icons/trending-down.svg' : '/icons/trending-up.svg';

    const isPerson = typeof svg === 'string' && svg.includes('person');
    const bgIconClass = [
        styles.cardBgIcon,
        isPerson ? styles.personBgIcon : '',
        svgClassName || ''
    ].filter(Boolean).join(' ');

    return (
        <div className={styles.smallStatsCard}>
            <Image 
                src={svg} 
                alt="" 
                width={110} 
                height={110} 
                className={bgIconClass} 
                style={svgStyle}
            />
            <div className={styles.cardTitle}>{header}</div>
            <div className={styles.cardMiddle}>
                {loading ? (
                    <div className={`${styles.skeleton} ${styles.skeletonValue}`} />
                ) : (
                    <span className={styles.cardValue}>{num}</span>
                )}
                {!loading && trend && (
                    <div className={`${styles.cardPill} ${pillClass}`}>
                        <div 
                            className={styles.trendIcon} 
                            style={{ 
                                maskImage: `url(${trendIconPath})`, 
                                WebkitMaskImage: `url(${trendIconPath})` 
                            }} 
                        />
                        {trend}
                    </div>
                )}
            </div>
            <div className={styles.cardSubtext}>
                {loading ? <div className={`${styles.skeleton} ${styles.skeletonText}`} /> : footer}
            </div>
        </div>
    );
};

export default SmallStatsCard;
