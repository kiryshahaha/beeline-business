import { Marker, useMap } from "@vis.gl/react-maplibre";
import Supercluster from "supercluster";
import { useMemo } from "react";
import { useMapView } from "@/hooks/useMapView";
import { ClusterPoint } from "./ClusterPoint";

export const ClusterComponent = ({ data, selectedObject, onSelectObject }) => {
  const { current: map } = useMap();
  const { zoom, bbox } = useMapView(map);

  const features = useMemo(
    () => data
      .filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude))
      .map((item) => ({
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
        },
      })),
    [data],
  );
  const itemByKey = useMemo(
    () => new Map(data.map((item) => [`${item.type}:${item.id}`, item])),
    [data],
  );
  const index = useMemo(() => {
    const cluster = new Supercluster({ radius: 40, maxZoom: 16, minPoints: 2 });
    cluster.load(features);
    return cluster;
  }, [features]);
  const clusters = useMemo(
    () => index.getClusters(bbox, Math.floor(zoom)),
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
        offset={isCluster ? undefined : overlapOffsets.get(`${type}:${feature.properties.id}`)}
        onClick={(event) => handleClick(event, feature)}
      >
        <ClusterPoint
          isCluster={isCluster}
          count={feature.properties.point_count}
          type={type}
          status={feature.properties.status}
          label={feature.properties.label}
          selected={isSelected}
        />
      </Marker>
    );
  });
};
