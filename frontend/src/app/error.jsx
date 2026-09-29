"use client";

import { useEffect } from "react";
import Link from "next/link";

export default function GlobalError({ error, reset }) {
  useEffect(() => {
    console.error("Unhandled runtime error in page:", error);
  }, [error]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0b0f19",
        color: "#f8fafc",
        padding: "24px",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <div
        style={{
          maxWidth: "480px",
          width: "100%",
          background: "#111827",
          borderRadius: "16px",
          padding: "32px",
          textAlign: "center",
          border: "1px solid #1f2937",
          boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.5)",
        }}
      >
        <div
          style={{
            width: "52px",
            height: "52px",
            borderRadius: "50%",
            background: "rgba(239, 68, 68, 0.12)",
            color: "#ef4444",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            margin: "0 auto 16px",
            fontSize: "26px",
          }}
        >
          ⚠️
        </div>
        <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "8px" }}>
          Что-то пошло не так
        </h2>
        <p
          style={{
            color: "#9ca3af",
            fontSize: "14px",
            lineHeight: "1.6",
            marginBottom: "24px",
          }}
        >
          {error?.message || "Произошла непредвиденная ошибка при загрузке данных панели управления."}
        </p>
        <div style={{ display: "flex", gap: "12px", justifyContent: "center" }}>
          <button
            onClick={() => reset()}
            style={{
              padding: "10px 20px",
              background: "#ffc800",
              color: "#1c1c1e",
              fontWeight: "600",
              borderRadius: "8px",
              border: "none",
              cursor: "pointer",
            }}
          >
            Попробовать снова
          </button>
          <Link
            href="/"
            style={{
              padding: "10px 20px",
              background: "#1f2937",
              color: "#f8fafc",
              fontWeight: "500",
              borderRadius: "8px",
              border: "1px solid #374151",
              textDecoration: "none",
              display: "inline-block",
            }}
          >
            На главную
          </Link>
        </div>
      </div>
    </div>
  );
}
