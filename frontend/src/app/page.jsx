"use client";

import MapComponent from "@/components/MapComponent";
import Search from "@/components/Search/Search";
import { useTickets } from "@/hooks/useTickets";
import { useRef } from "react";

export default function Home() {
  const mapRef = useRef(null);

  const { tickets } = useTickets({
    limit: 20,
    offset: 0,
  });

  return (
    <main style={{ height: "100dvh", position: "relative" }}>
      <div style={{ position: "absolute", top: 22, left: 22, zIndex: 10 }}>
        <Search />
      </div>
      <MapComponent mapRef={mapRef} tickets={tickets} />
    </main>
  );
}
