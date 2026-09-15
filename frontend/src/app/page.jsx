"use client";

import MapComponent from "@/components/MapComponent";
import { useRef } from "react";

export default function Home() {
  const mapRef = useRef(null);
  return (
    <main style={{ height: "100dvh" }}>
      <MapComponent mapRef={mapRef} />
    </main>
  );
}
