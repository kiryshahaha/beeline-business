"use client";

import React, { useEffect, useRef } from "react";
import styles from "./StarrySky.module.css";

const STAR_COLORS = [
  "rgba(255, 255, 255, ",
  "rgba(240, 244, 255, ",
  "rgba(255, 245, 220, ",
  "rgba(255, 215, 64, ", // subtle gold
  "rgba(180, 220, 255, ", // blue star
];

export default function StarrySky() {
  const bgCanvasRef = useRef(null);

  useEffect(() => {
    const bgCanvas = bgCanvasRef.current;
    if (!bgCanvas) return;

    const bgCtx = bgCanvas.getContext("2d");

    let width = (bgCanvas.width = window.innerWidth);
    let height = (bgCanvas.height = window.innerHeight);

    const handleResize = () => {
      if (!bgCanvas) return;
      width = bgCanvas.width = window.innerWidth;
      height = bgCanvas.height = window.innerHeight;
    };
    window.addEventListener("resize", handleResize);

    // Генерируем звёздное небо
    const starCount = Math.floor((width * height) / 4000) + 140;
    const stars = Array.from({ length: starCount }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      size: Math.random() < 0.82 ? Math.random() * 1.2 + 0.5 : Math.random() * 2.0 + 1.2,
      baseAlpha: Math.random() * 0.6 + 0.25,
      twinkleSpeed: Math.random() * 0.03 + 0.008,
      phase: Math.random() * Math.PI * 2,
      color: STAR_COLORS[Math.floor(Math.random() * STAR_COLORS.length)],
    }));

    // Туманности (космическая глубина)
    const nebulae = [
      { x: width * 0.2, y: height * 0.3, r: width * 0.35, color: "rgba(18, 24, 45, 0.45)" },
      { x: width * 0.8, y: height * 0.4, r: width * 0.4, color: "rgba(28, 22, 40, 0.35)" },
      { x: width * 0.5, y: height * 0.8, r: width * 0.45, color: "rgba(12, 20, 32, 0.4)" },
    ];

    let animationFrameId;

    const render = (time) => {
      // --- Рисуем космический фон ---
      bgCtx.fillStyle = "#0c0d12";
      bgCtx.fillRect(0, 0, width, height);

      // Отрисовка мягких космических туманностей
      nebulae.forEach((neb) => {
        const grad = bgCtx.createRadialGradient(neb.x, neb.y, 0, neb.x, neb.y, neb.r);
        grad.addColorStop(0, neb.color);
        grad.addColorStop(1, "transparent");
        bgCtx.fillStyle = grad;
        bgCtx.beginPath();
        bgCtx.arc(neb.x, neb.y, neb.r, 0, Math.PI * 2);
        bgCtx.fill();
      });

      // Отрисовка мерцающих звёзд
      stars.forEach((star) => {
        star.phase += star.twinkleSpeed;
        const alpha = star.baseAlpha * (0.65 + 0.35 * Math.sin(star.phase));
        bgCtx.fillStyle = `${star.color}${alpha.toFixed(3)})`;
        bgCtx.beginPath();
        bgCtx.arc(star.x, star.y, star.size, 0, Math.PI * 2);
        bgCtx.fill();

        // Небольшое свечение для крупных звёзд
        if (star.size > 2.0 && alpha > 0.6) {
          bgCtx.fillStyle = `rgba(255, 255, 255, ${(alpha * 0.18).toFixed(3)})`;
          bgCtx.beginPath();
          bgCtx.arc(star.x, star.y, star.size * 2.8, 0, Math.PI * 2);
          bgCtx.fill();
        }
      });

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas ref={bgCanvasRef} className={styles.bgCanvas} />
  );
}
