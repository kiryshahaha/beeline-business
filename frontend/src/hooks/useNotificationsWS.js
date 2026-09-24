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
    // Если токена нет, не пытаемся подключиться
    if (!token) return;

    // Формируем URL для вебсокета (меняем http/https на ws/wss)
    const baseUrl = process.env.NEXT_PUBLIC_ENDPOINT || "http://localhost:8000/api/v1";
    // Меняем localhost на 127.0.0.1, чтобы избежать проблем с IPv6 в браузере (когда uvicorn слушает только IPv4)
    const wsUrl = baseUrl.replace(/^http/, "ws").replace("localhost", "127.0.0.1") + "/notifications/ws";

    let reconnectTimer;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        // Сразу при открытии отправляем токен
        ws.send(JSON.stringify({ type: "authenticate", token }));
        setIsConnected(true);

        // Настраиваем пинги каждые 30 секунд для удержания соединения
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
            console.log("WebSocket аутентифицирован для пользователя", data.user_id);
          } else if (data.type === "pong") {
            // Игнорируем понг
          } else {
            // Пришло реальное бизнес-событие (новое уведомление)
            console.log("Новое уведомление по WS:", data);
            
            // Включаем красную точку
            setHasUnread(true);
            
            // Инвалидируем запросы заявок, чтобы они перезагрузились в фоне
            queryClient.invalidateQueries({ queryKey: ["ticketsList"] });
          }
        } catch (err) {
          console.error("Ошибка парсинга WS сообщения:", err);
        }
      };

      ws.onclose = (event) => {
        setIsConnected(false);
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        
        // 1008 - токен недействителен (возможно протух), не делаем автореконнект
        if (event.code === 1008) {
          console.error("WS закрыт бэкендом (Недействительный токен)");
          return;
        }
        
        // В других случаях пытаемся переподключиться через 3 секунды
        reconnectTimer = setTimeout(() => {
          connect();
        }, 3000);
      };

      ws.onerror = (err) => {
        console.error("WebSocket ошибка:", err);
        ws.close();
      };
    };

    connect();

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [token, queryClient]);

  // Функция для сброса индикатора непрочитанных
  const clearUnread = () => setHasUnread(false);

  return { isConnected, hasUnread, clearUnread };
}
