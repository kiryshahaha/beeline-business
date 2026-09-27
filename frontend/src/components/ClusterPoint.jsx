import styles from "./MapComponent.module.css";

export const ClusterPoint = ({ isCluster, count, type, status, label, selected }) => {
  if (isCluster) {
    return (
      <button
        type="button"
        className={styles.clusterMarker}
        aria-label={`Приблизить группу из ${count} объектов`}
      >
        {count}
      </button>
    );
  }

  const symbols = { ticket: "З", worker: "И", office: "О" };
  return (
    <button
      type="button"
      className={`${styles.geoMarker} ${styles[`geoMarker_${type}`]} ${selected ? styles.selectedMarker : ""}`}
      data-status={status}
      aria-label={label}
      title={label}
    >
      {type === "ticket" ? label.match(/#(\d+)/)?.[1] : symbols[type]}
    </button>
  );
};
