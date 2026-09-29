import { useEffect, useState, useRef } from "react";
import { useAuth } from "@/providers/AuthProvider";
import { useQueryClient } from "@tanstack/react-query";

export function useNotificationsWS() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const [hasUnread, setHasUnread] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);
  const pingIntervalRef = useRef(null);

  useEffect(() => {
    if (!token) return;

    let cancelled = false;

    const rawBaseUrl =
      process.env.NEXT_PUBLIC_API_URL ||
      process.env.NEXT_PUBLIC_ENDPOINT ||
      "http://localhost:8000/api/v1";

    const normalizedBase = rawBaseUrl.endsWith("/api/v1")
      ? rawBaseUrl
      : `${rawBaseUrl.replace(/\/+$/, "")}/api/v1`;

    const wsUrl =
      normalizedBase.replace(/^http/, "ws").replace("localhost", "127.0.0.1") +
      "/notifications/ws";

    let reconnectTimer;

    const connect = () => {
      if (cancelled) return;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) {
          ws.close();
          return;
        }

        const savedLastId =
          typeof window !== "undefined"
            ? parseInt(localStorage.getItem("beeline_last_event_id") || "0", 10)
            : 0;

        const authPayload = {
          type: "authenticate",
          token,
          ...(savedLastId > 0 ? { last_event_id: savedLastId } : {}),
        };

        ws.send(JSON.stringify(authPayload));
        setIsConnected(true);

        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "authenticated") {
            // Аутентифицирован
          } else if (data.type === "pong") {
            // Понг
          } else {
            setHasUnread(true);

            if (data.id && typeof window !== "undefined") {
              localStorage.setItem("beeline_last_event_id", String(data.id));
            }

            // Инвалидируем все связанные сущности, чтобы интерфейс диспетчера обновлялся в реальном времени
            queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
            queryClient.invalidateQueries({ queryKey: ["tickets"] });
            queryClient.invalidateQueries({ queryKey: ["fastStats"] });
            queryClient.invalidateQueries({ queryKey: ["fast-stats"] });
            queryClient.invalidateQueries({ queryKey: ["ticketsSummary"] });
            queryClient.invalidateQueries({ queryKey: ["tickets-summary"] });
            queryClient.invalidateQueries({ queryKey: ["brigadesWorkload"] });
            queryClient.invalidateQueries({ queryKey: ["routesList"] });
            queryClient.invalidateQueries({ queryKey: ["routes"] });
            queryClient.invalidateQueries({ queryKey: ["completionReviews"] });
            queryClient.invalidateQueries({ queryKey: ["notificationsHistory"] });
          }
        } catch (err) {
          console.error("Ошибка парсинга WS сообщения:", err);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);

        if (cancelled) return;

        if (event.code === 1008) {
          return;
        }

        reconnectTimer = setTimeout(() => {
          connect();
        }, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [token, queryClient]);

  const clearUnread = () => {
    setHasUnread(false);
  };

  return { hasUnread, isConnected, clearUnread };
}
