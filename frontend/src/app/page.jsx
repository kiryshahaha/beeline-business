"use client";

import MapComponent from "@/components/MapComponent";
import { useTickets } from "@/hooks/useTickets";
import { useRef } from "react";

export default function Home() {
  const mapRef = useRef(null);

  const { tickets } = useTickets({
    limit: 20,
    offset: 0,
  });

  return (
    <main style={{ height: "100dvh" }}>
      <MapComponent mapRef={mapRef} tickets={tickets} />
    </main>
  );
}
