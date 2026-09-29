// frontend/src/hooks/worker/useWorkerWS.js
import { useEffect, useRef, useState, useCallback } from "react";
import { useAuth } from "@/providers/AuthProvider";
import { useQueryClient } from "@tanstack/react-query";
import { API_BASE, refreshSession } from "@/lib/apiFetch";
import { fetchNotifications } from "@/lib/worker/api";

function formatNotificationToast(kind, data, ticketId) {
  const tId = ticketId || data?.ticket_id;
  const numPrefix = tId ? `№${tId}` : "";

  switch (kind) {
    case "ticket_assigned":
      return `Вам назначена заявка ${numPrefix}: ${data?.title || ""}`.trim();
    case "ticket_unassigned":
      return `Заявка ${numPrefix} снята с вас: ${data?.reason_text || data?.reason || "причина не указана"}`.trim();
    case "ticket_rescheduled":
      return `Заявка ${numPrefix} перенесена${data?.from && data?.to ? ` с ${data.from} на ${data.to}` : ""}. ${data?.reason_text || ""}`.trim();
    case "ticket_window_changed":
      return `По заявке ${numPrefix} изменено окно визита. ${data?.reason_text || ""}`.trim();
    case "ticket_completion_confirmed":
      return `Диспетчер подтвердил выполнение заявки ${numPrefix}`.trim();
    case "ticket_completion_rejected":
      return `Диспетчер вернул заявку ${numPrefix}: ${data?.reason || "причина не указана"}`.trim();
    default:
      return data?.message || data?.title || `Событие по заявке ${numPrefix}`;
  }
}

export function useWorkerWS() {
  const { token, user } = useAuth();
  const queryClient = useQueryClient();
  const [toasts, setToasts] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef(null);
  const pingIntervalRef = useRef(null);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((text, type = "info") => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((prev) => [...prev.slice(-4), { id, text, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 6000);
  }, []);

  useEffect(() => {
    if (!token || !user?.id) return;

    let cancelled = false;
    let reconnectTimer = null;
    const storageKey = `worker_last_event_id_${user.id}`;

    const wsUrl =
      API_BASE.replace(/^http/, "ws").replace("localhost", "127.0.0.1") +
      "/notifications/ws";

    const connect = () => {
      if (cancelled) return;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) {
          ws.close();
          return;
        }

        const savedLastId = parseInt(localStorage.getItem(storageKey) || "0", 10);
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

      ws.onmessage = async (event) => {
        try {
          const payload = JSON.parse(event.data);

          if (payload.type === "authenticated" || payload.type === "pong") {
            return;
          }

          if (payload.type === "replay_truncated") {
            const savedLastId = parseInt(localStorage.getItem(storageKey) || "0", 10);
            try {
              const missed = await fetchNotifications(100, savedLastId);
              if (Array.isArray(missed) && missed.length > 0) {
                const maxId = Math.max(...missed.map((m) => m.id));
                localStorage.setItem(storageKey, String(maxId));
              }
            } catch {
              // ignore
            }
            queryClient.invalidateQueries({ queryKey: ["myDay"] });
            queryClient.invalidateQueries({ queryKey: ["notifications"] });
            return;
          }

          // Regular notification event
          if (payload.id) {
            localStorage.setItem(storageKey, String(payload.id));
          }

          setUnreadCount((c) => c + 1);

          const kind = (payload.kind || "").toLowerCase();
          const toastText = formatNotificationToast(kind, payload.data, payload.ticket_id);
          const toastType = kind.includes("rejected") || kind.includes("unassigned")
            ? "warning"
            : kind.includes("confirmed")
            ? "success"
            : "info";

          addToast(toastText, toastType);

          // Invalidate related queries
          queryClient.invalidateQueries({ queryKey: ["myDay"] });
          queryClient.invalidateQueries({ queryKey: ["notifications"] });
          if (payload.ticket_id) {
            queryClient.invalidateQueries({ queryKey: ["ticketChanges", payload.ticket_id] });
            queryClient.invalidateQueries({ queryKey: ["ticket", payload.ticket_id] });
          }
        } catch (err) {
          console.error("Worker WS parse error:", err);
        }
      };

      ws.onclose = async (event) => {
        setIsConnected(false);
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);

        if (cancelled) return;

        if (event.code === 1008) {
          // Token expired, refresh and reconnect
          try {
            await refreshSession();
            reconnectTimer = setTimeout(connect, 1000);
          } catch {
            // failed to refresh
          }
          return;
        }

        const delay = event.code === 1013 ? 5000 : 3000;
        reconnectTimer = setTimeout(connect, delay);
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
  }, [token, user?.id, queryClient, addToast]);

  return {
    isConnected,
    unreadCount,
    clearUnreadCount: () => setUnreadCount(0),
    toasts,
    removeToast,
  };
}
