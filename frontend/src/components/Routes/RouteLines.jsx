"use client";

import { Source, Layer } from "@vis.gl/react-maplibre";

export default function RouteLines({ routesGeoJson }) {
  if (!routesGeoJson || !routesGeoJson.features || routesGeoJson.features.length === 0) {
    return null;
  }

  return (
    <Source id="routes-source" type="geojson" data={routesGeoJson}>
      {/* 0. Невидимая область для легкого наведения курсора */}
      <Layer
        id="routes-hit-area"
        type="line"
        layout={{ "line-join": "round", "line-cap": "round" }}
        paint={{
          "line-color": "#ffffff",
          "line-width": 14,
          "line-opacity": 0.001,
        }}
      />

      {/* 1. Темная контрастная окантовка для максимальной четкости на белой карте */}
      <Layer
        id="routes-casing"
        type="line"
        layout={{ "line-join": "round", "line-cap": "round" }}
        paint={{
          "line-color": "#0F172A",
          "line-width": [
            "case",
            ["boolean", ["get", "isSelected"], false],
            7.5,
            4.5,
          ],
          "line-opacity": [
            "case",
            ["boolean", ["get", "isSelected"], false],
            0.9,
            ["boolean", ["get", "isDimmed"], false],
            0.15,
            0.45,
          ],
        }}
      />

      {/* 2. Основная цветная линия маршрута по дорогам */}
      <Layer
        id="routes-line"
        type="line"
        layout={{ "line-join": "round", "line-cap": "round" }}
        paint={{
          "line-color": ["coalesce", ["get", "color"], "#FFB800"],
          "line-width": [
            "case",
            ["boolean", ["get", "isSelected"], false],
            5.0,
            3.0,
          ],
          "line-opacity": [
            "case",
            ["boolean", ["get", "isSelected"], false],
            1.0,
            ["boolean", ["get", "isDimmed"], false],
            0.22,
            0.9,
          ],
        }}
      />
    </Source>
  );
}
