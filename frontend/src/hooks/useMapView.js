import { useEffect, useState } from "react";

export function useMapView(mapref) {
  const [zoom, setZoom] = useState(2);
  const [bbox, setBbox] = useState([]);
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
    mapref.on("move", updateMapData);
    return () => {
      mapref.off("move", updateMapData);
    };
  }, [mapref]);

  return { zoom, bbox };
}
