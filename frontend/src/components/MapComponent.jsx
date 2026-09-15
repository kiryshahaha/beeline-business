"use client";

import {
  FullscreenControl,
  GeolocateControl,
  Map,
  NavigationControl,
  ScaleControl,
} from "@vis.gl/react-maplibre";
import { ProjectionControl } from "./controls/ProjectionControl";
import "maplibre-gl/dist/maplibre-gl.css";

export default function MapComponent({ mapRef, tickets }) {
  // console.log(tickets);

  return (
    <Map
      styleDiffing
      hash
      keyboard
      light={{
        anchor: "viewport",
        "position-transition": { duration: 1000 },
        color: "#FFD38A",
      }}
      attributionControl={false}
      sky={{
        "sky-color": "#88C6FC",
      }}
      id="mainMap"
      maxPitch={75}
      reuseMaps
      zoomSnap={1}
      maxZoom={20}
      minZoom={0}
      ref={mapRef}
      // Надо будет вынести для разных стилей карты в отдельный обьект
      mapStyle={`https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`}
    >
      {/* Компоненты ниже отвечают за кнопки управления */}
      <NavigationControl visualizePitch visualizeRoll></NavigationControl>
      <FullscreenControl></FullscreenControl>
      <GeolocateControl></GeolocateControl>
      <ScaleControl></ScaleControl>
      <ProjectionControl></ProjectionControl>
    </Map>
  );
}
