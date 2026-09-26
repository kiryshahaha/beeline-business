"use client";

import { useEffect, useRef, useState } from "react";

const R = 28;       // радиус гекса
const GAP = 4;      // зазор между гексами

// Вершины flat-top шестиугольника
function hexPoints(cx, cy, r) {
  return Array.from({ length: 6 }, (_, i) => {
    const angle = (Math.PI / 180) * (60 * i - 30);
    return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
  }).join(" ");
}

// Строим массив позиций под нужный viewport
function buildHexes(vw, vh) {
  const colW = Math.sqrt(3) * (R + GAP / 2);
  const rowH = (2 * R + GAP) * 0.75;
  const cols = Math.ceil(vw / colW) + 2;
  const rows = Math.ceil(vh / rowH) + 2;

  const hexes = [];
  for (let row = 0; row < rows; row++) {
    for (let col = 0; col < cols; col++) {
      const x = col * colW + (row % 2 === 0 ? 0 : colW / 2);
      const y = row * rowH;
      hexes.push({ x, y, id: `${col}-${row}` });
    }
  }
  return hexes;
}

export default function HexGrid() {
  const svgRef = useRef(null);
  const [hexes, setHexes] = useState([]);

  // Пересчитываем сетку при изменении размера окна
  useEffect(() => {
    const update = () => setHexes(buildHexes(window.innerWidth, window.innerHeight));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // Анимация случайных вспышек
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !hexes.length) return;

    const polys = Array.from(svg.querySelectorAll("polygon[data-hex]"));
    if (!polys.length) return;

    const timers = new Set();

    const FADE_IN  = 600;   // ms — появление
    const HOLD     = 1800;  // ms — горит
    const FADE_OUT = 1200;  // ms — угасание
    const INTERVAL = 700;   // ms — пауза (одновременно ~7 гексов светятся)

    const flash = () => {
      const el = polys[Math.floor(Math.random() * polys.length)];
      if (el) {
        el.style.transition = `opacity ${FADE_IN}ms ease`;
        el.style.opacity = (Math.random() * 0.35 + 0.2).toFixed(2);
        const t = setTimeout(() => {
          el.style.transition = `opacity ${FADE_OUT}ms ease`;
          el.style.opacity = "0";
          timers.delete(t);
        }, FADE_IN + HOLD);
        timers.add(t);
      }
      const next = setTimeout(flash, INTERVAL);
      timers.add(next);
    };

    flash();
    return () => timers.forEach(clearTimeout);
  }, [hexes]);

  return (
    <svg
      ref={svgRef}
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        pointerEvents: "none",
        zIndex: 0,
      }}
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <filter id="hex-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Контуры */}
      {hexes.map((h) => (
        <polygon
          key={`o-${h.id}`}
          points={hexPoints(h.x, h.y, R)}
          fill="none"
          stroke="rgba(255,200,0,0.06)"
          strokeWidth="1"
        />
      ))}

      {/* Светящиеся */}
      {hexes.map((h) => (
        <polygon
          key={`g-${h.id}`}
          data-hex="1"
          points={hexPoints(h.x, h.y, R)}
          fill="#FFC800"
          opacity="0"
          filter="url(#hex-glow)"
          style={{ willChange: "opacity" }}
        />
      ))}
    </svg>
  );
}
