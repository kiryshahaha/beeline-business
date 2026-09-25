export const ClusterPoint = ({ isCluster, clusterData }) => {
  if (isCluster) {
    return (
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          background: "#1677ff",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          border: "2px solid #fff",
          boxShadow: "0 1px 4px rgba(0,0,0,0.3)",
        }}
      >
        {clusterData.properties.point_count_abbreviated}
      </div>
    );
  }
  // Просто точка
  return (
    <div
      style={{
        cursor: "pointer",
        width: 16,
        aspectRatio: 1,
        borderRadius: "50%",
        background: "#1677ff",
        border: "2px solid #fff",
        boxShadow: "0 1px 4px rgba(0,0,0,0.3)",
      }}
    />
  );
};
