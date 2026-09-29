import { Marker, useMap } from "@vis.gl/react-maplibre";
import Supercluster from "supercluster";
import { useMemo } from "react";
import { useMapView } from "@/hooks/useMapView";
import { ClusterPoint } from "./ClusterPoint";
import { isTicketUrgent } from "@/utils/ticketUtils";

export const ClusterComponent = ({ data, selectedObject, onSelectObject }) => {
  const { current: map } = useMap();
  const { zoom, bbox } = useMapView(map);

  const features = useMemo(
    () => data
      .filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
      .map((item) => {
        const isUrgent = item.type === "ticket" && isTicketUrgent(item.data);

        let title = item.label;
        let address = "";
        let extra = null;
        let transportType = "car";
        let isOnLine = true;

        if (item.type === "ticket") {
          title = item.data?.title || item.label;
          address = item.data?.location?.address || "";
          if (item.data?.visit_window_start) {
            try {
              const start = new Date(item.data.visit_window_start).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
              });
              const end = item.data.visit_window_end
                ? new Date(item.data.visit_window_end).toLocaleTimeString("ru-RU", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })
                : null;
              extra = end ? `Окно: ${start} - ${end}` : `Визит: ${start}`;
            } catch {
              // ignore invalid date
            }
          }
        } else if (item.type === "worker") {
          const names = [item.data?.name, item.data?.surname, item.data?.lastname].filter(Boolean);
          title = names.length > 0 ? names.join(" ") : item.label;
          address = item.data?.location?.address || "";
          transportType = item.data?.worker_profile?.transport_type || "car";
          isOnLine = item.data?.worker_profile?.is_on_line ?? true;

          const transportLabels = {
            car: "Авто",
            bicycle: "Вело/СИМ",
            walking: "Пешком",
            public_transport: "Транспорт",
          };
          const parts = [];
          if (item.data?.brigade_name) parts.push(item.data.brigade_name);
          parts.push(transportLabels[transportType] || "Транспорт");
          extra = parts.join(" • ");
        } else if (item.type === "office") {
          title = item.data?.office_name || item.label;
          address = item.data?.address || "";
          if (item.data?.city) {
            extra = [item.data.city, item.data.district].filter(Boolean).join(", ");
          }
        }

        return {
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [item.longitude, item.latitude],
          },
          properties: {
            id: item.id,
            type: item.type,
            label: item.label,
            status: item.data?.status,
            priority: item.data?.priority,
            category: item.data?.category,
            isUrgent,
            title,
            address,
            extra,
            transportType,
            isOnLine,
          },
        };
      }),
    [data],
  );
  const itemByKey = useMemo(
    () => new Map(data.map((item) => [`${item.type}:${item.id}`, item])),
    [data],
  );
  const index = useMemo(() => {
    let customRadius = 60;
    try {
      const saved = typeof window !== "undefined" ? localStorage.getItem("beeline_cluster_radius") : null;
      if (saved) {
        const num = Number(saved);
        if (num >= 20 && num <= 150) customRadius = num;
      }
    } catch {}

    const cluster = new Supercluster({
      radius: customRadius,
      maxZoom: 16,
      minPoints: 2,
      map: (props) => ({
        urgentCount: props.isUrgent ? 1 : 0,
        ticketCount: props.type === "ticket" ? 1 : 0,
        workerCount: props.type === "worker" ? 1 : 0,
        officeCount: props.type === "office" ? 1 : 0,
      }),
      reduce: (acc, props) => {
        acc.urgentCount += props.urgentCount;
        acc.ticketCount += props.ticketCount;
        acc.workerCount += props.workerCount;
        acc.officeCount += props.officeCount;
      },
    });
    cluster.load(features);
    return cluster;
  }, [features]);
  const clusters = useMemo(
    () => index.getClusters(bbox, Math.round(zoom)),
    [bbox, index, zoom],
  );
  const overlapOffsets = useMemo(() => {
    if (zoom < 16) return new Map();
    const overlapping = new Map();
    clusters.forEach((feature) => {
      if (feature.properties.cluster) return;
      const key = feature.geometry.coordinates.map((coordinate) => coordinate.toFixed(6)).join(":");
      overlapping.set(key, [...(overlapping.get(key) || []), feature]);
    });
    const offsets = new Map();
    overlapping.forEach((featuresAtPoint) => {
      if (featuresAtPoint.length < 2) return;
      featuresAtPoint
        .sort((a, b) => `${a.properties.type}:${a.properties.id}`.localeCompare(`${b.properties.type}:${b.properties.id}`))
        .forEach((feature, position) => {
          const angle = (position / featuresAtPoint.length) * Math.PI * 2;
          offsets.set(`${feature.properties.type}:${feature.properties.id}`, [
            Math.cos(angle) * 24,
            Math.sin(angle) * 24,
          ]);
        });
    });
    return offsets;
  }, [clusters, zoom]);

  const handleClick = (event, feature) => {
    event.originalEvent.stopPropagation();
    if (feature.properties.cluster) {
      const [longitude, latitude] = feature.geometry.coordinates;
      map.flyTo({
        center: [longitude, latitude],
        zoom: index.getClusterExpansionZoom(feature.properties.cluster_id),
        duration: 500,
      });
      return;
    }

    const item = itemByKey.get(`${feature.properties.type}:${feature.properties.id}`);
    if (item) onSelectObject(item);
  };

  return clusters.map((feature) => {
    const [longitude, latitude] = feature.geometry.coordinates;
    const isCluster = Boolean(feature.properties.cluster);
    const type = feature.properties.type;
    const isSelected = !isCluster && selectedObject?.type === type
      && selectedObject.id === feature.properties.id;

    return (
      <Marker
        key={isCluster ? `cluster-${feature.properties.cluster_id}` : `${type}-${feature.properties.id}`}
        longitude={longitude}
        latitude={latitude}
        anchor="center"
        offset={isCluster ? undefined : overlapOffsets.get(`${type}:${feature.properties.id}`)}
        onClick={(event) => handleClick(event, feature)}
      >
        <ClusterPoint
          isCluster={isCluster}
          count={feature.properties.point_count}
          urgentCount={feature.properties.urgentCount}
          ticketCount={feature.properties.ticketCount}
          workerCount={feature.properties.workerCount}
          officeCount={feature.properties.officeCount}
          type={type}
          id={feature.properties.id}
          status={feature.properties.status}
          isUrgent={feature.properties.isUrgent}
          priority={feature.properties.priority}
          transportType={feature.properties.transportType}
          isOnLine={feature.properties.isOnLine}
          label={feature.properties.label}
          title={feature.properties.title}
          address={feature.properties.address}
          extra={feature.properties.extra}
          selected={isSelected}
          hasActiveSelection={Boolean(selectedObject)}
        />
      </Marker>
    );
  });
};
