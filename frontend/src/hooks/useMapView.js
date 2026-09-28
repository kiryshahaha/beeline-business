import { useEffect, useState } from "react";

export function useMapView(mapref) {
  const [zoom, setZoom] = useState(2);
  const [bbox, setBbox] = useState([-180, -85, 180, 85]);
  useEffect(() => {
    if (!mapref) return;

    const updateMapData = () => {
      const bounds = mapref.getBounds();

      setZoom(mapref.getZoom());

      setBbox([
        bounds.getWest(),
        bounds.getSouth(),
        bounds.getEast(),
        bounds.getNorth(),
      ]);
    };
    updateMapData();
    mapref.on("moveend", updateMapData);
    return () => {
      mapref.off("moveend", updateMapData);
    };
  }, [mapref]);

  return { zoom, bbox };
}
