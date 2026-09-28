import { useEffect, useRef, useState } from "react";

export function useMapView(mapref) {
  const [zoom, setZoom] = useState(2);
  const [bbox, setBbox] = useState([-180, -85, 180, 85]);
  const rafIdRef = useRef(null);

  useEffect(() => {
    if (!mapref) return;

    const updateMapData = () => {
      if (!mapref || typeof mapref.getBounds !== "function") return;
      const bounds = mapref.getBounds();
      if (!bounds) return;

      setZoom(mapref.getZoom());

      // Добавляем небольшой буфер (5%) по краям вьюпорта,
      // чтобы кластеры у границ экрана не мерцали при быстром панорамировании
      const west = bounds.getWest();
      const south = bounds.getSouth();
      const east = bounds.getEast();
      const north = bounds.getNorth();
      const dx = (east - west) * 0.05;
      const dy = (north - south) * 0.05;

      setBbox([
        Math.max(-180, west - dx),
        Math.max(-85, south - dy),
        Math.min(180, east + dx),
        Math.min(85, north + dy),
      ]);
    };

    const handleRealtimeUpdate = () => {
      if (rafIdRef.current) return;
      rafIdRef.current = requestAnimationFrame(() => {
        updateMapData();
        rafIdRef.current = null;
      });
    };

    const handleMoveEnd = () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      updateMapData();
    };

    // Первоначальный расчёт
    updateMapData();

    // Обновление в реальном времени при любом движении/зуме/скролле
    mapref.on("move", handleRealtimeUpdate);
    mapref.on("zoom", handleRealtimeUpdate);
    mapref.on("moveend", handleMoveEnd);

    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      mapref.off("move", handleRealtimeUpdate);
      mapref.off("zoom", handleRealtimeUpdate);
      mapref.off("moveend", handleMoveEnd);
    };
  }, [mapref]);

  return { zoom, bbox };
}
