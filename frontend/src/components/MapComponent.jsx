"use client";

import { Map } from "@vis.gl/react-maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import { ClusterComponent } from "./ClusterComponent";
import { useState } from "react";
import OfficePopup from "./OfficePopup";

export default function MapComponent({ mapRef, props }) {
  const { officesFullInfo } = props;

  const [popUpData, setPopUpData] = useState(null);

  return (
    <Map
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
      }}
      ref={mapRef}
      mapStyle={`https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${process.env.NEXT_PUBLIC_MAPTILER_API_KEY}`}
      attributionControl={false}
      x
      maxZoom={20}
      minZoom={0}
      maxPitch={75}
      reuseMaps
      keyboard
      hash
    >
      {popUpData && (
        <OfficePopup
          data={popUpData.popUpData}
          longitude={popUpData.lng}
          latitude={popUpData.lat}
          onClose={() => setPopUpData(null)}
        />
      )}
      <ClusterComponent data={officesFullInfo} setPopUpData={setPopUpData} />
    </Map>
  );
}
