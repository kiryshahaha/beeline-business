import styles from "./Markers.module.css";

export default function PointTooltip({
  tag,
  tagVariant = "planned",
  text,
  subtext,
}) {
  if (!text && !tag) return null;

  return (
    <div className={styles.pointTooltip} role="tooltip">
      {tag && (
        <div className={styles.pointTooltipHeader}>
          <span
            className={`${styles.pointTooltipTag} ${
              styles[`pointTooltipTag_${tagVariant}`] || ""
            }`}
          >
            {tag}
          </span>
        </div>
      )}
      {text && <div className={styles.pointTooltipTitle}>{text}</div>}
      {subtext && <div className={styles.pointTooltipSub}>{subtext}</div>}
      <div className={styles.pointTooltipArrow} />
    </div>
  );
}
