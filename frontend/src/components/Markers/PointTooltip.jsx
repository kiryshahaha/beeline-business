import styles from "./Markers.module.css";

export default function PointTooltip({
  tag,
  tagVariant = "planned",
  text,
  subtext,
}) {
  if (!text && !tag) return null;

  return (
    <div className={styles.microChip} role="tooltip">
      {tag && (
        <span
          className={`${styles.microChipTag} ${
            styles[`microChipTag_${tagVariant}`] || ""
          }`}
        >
          {tag}
        </span>
      )}
      {text && <span className={styles.microChipText}>{text}</span>}
      {subtext && <span className={styles.microChipSub}>{subtext}</span>}
    </div>
  );
}
