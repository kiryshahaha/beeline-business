import { Marker, useMap } from "@vis.gl/react-maplibre";

import { ClusterPoint } from "./ClusterPoint";
import Supercluster from "supercluster";
import { useMemo } from "react";
import { useMapView } from "@/hooks/useMapView";

const radiusPixels = 35;
const zoomLevel = 5;

export const ClusterComponent = ({ data, setPopUpData }) => {
  const { current: mapref } = useMap();

  const { zoom, bbox } = useMapView(mapref);

  const features = useMemo(() => {
    return data
      .filter((item) => item.latitude != null && item.longitude != null)
      .map((item) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [item.longitude, item.latitude],
        },
        properties: {
          id: item.id,
        },
      }));
  }, [data]);

  const index = useMemo(() => {
    const cluster = new Supercluster({
      radius: radiusPixels,
      maxZoom: zoomLevel,
    });

    cluster.load(features);

    return cluster;
  }, [features]);

  const clusters = useMemo(() => {
    return index.getClusters(bbox, Math.floor(zoom));
  }, [index, bbox, zoom]);

  const handleClick = (e, lng, lat, cluster, isCluster) => {
    e.originalEvent.stopPropagation();
    e.originalEvent.preventDefault();

    if (!isCluster) {
      const popUpData = data.find((item) => item.id == cluster.properties?.id);

      setPopUpData({
        lng,
        lat,
        popUpData,
      });
    }

    if (isCluster) {
      const zoomToExpandCluster = index.getClusterExpansionZoom(
        cluster.properties.cluster_id,
      );

      mapref.flyTo({
        center: [lng, lat],
        zoom: zoomToExpandCluster,
        duration: 1000,
      });
    }
  };

  return (
    <>
      {clusters.map((cluster) => {
        const [lng, lat] = cluster.geometry.coordinates;
        const isCluster = cluster.properties?.cluster;

        return (
          <Marker
            key={
              isCluster ? cluster.properties.cluster_id : cluster.properties.id
            }
            longitude={lng}
            latitude={lat}
            clickTolerance={100}
            onClick={(e) => handleClick(e, lng, lat, cluster, isCluster)}
          >
            <ClusterPoint isCluster={isCluster} clusterData={cluster} />
          </Marker>
        );
      })}
    </>
  );
};
