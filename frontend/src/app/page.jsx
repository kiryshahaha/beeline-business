"use client";

import MapComponent from "@/components/MapComponent";
import Search from "@/components/Search/Search";
import TicketsStatuses from "@/components/TicketsStatuses/TicketsStatuses";
import Notifications from "@/components/Notifications/Notifications";
import Layers from "@/components/Layers/Layers";
import Menu from "@/components/Menu/Menu";
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
      <div style={{
        position: "absolute",
        inset: 22,
        pointerEvents: "none",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        zIndex: 10
      }}>
        {/* Верхняя панель */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div style={{ pointerEvents: "auto" }}><Search /></div>
          <div style={{ pointerEvents: "auto" }}><Notifications /></div>
        </div>
        
        {/* Нижняя панель */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          <div style={{ display: "flex", gap: "16px", alignItems: "flex-end", marginLeft: "75px" }}>
            <div style={{ pointerEvents: "auto" }}><Layers mapRef={mapRef} /></div>
            <div style={{ pointerEvents: "auto" }}><Menu /></div>
          </div>
          <div style={{ pointerEvents: "auto" }}><TicketsStatuses /></div>
        </div>
      </div>
      <MapComponent mapRef={mapRef} tickets={tickets} />
    </main>
  );
}
