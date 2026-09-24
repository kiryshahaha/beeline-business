import { updateToken } from "@/lib/tokenBus";

const BASE = process.env.NEXT_PUBLIC_ENDPOINT;

let isRefreshing = false;
let refreshSubscribers = [];

function onTokenRefreshed(newToken) {
  refreshSubscribers.forEach((cb) => cb(newToken));
  refreshSubscribers = [];
}

function addRefreshSubscriber(cb) {
  refreshSubscribers.push(cb);
}

async function tryRefresh() {
  // refresh_token хранится в httpOnly cookie — браузер шлёт его сам через credentials: "include"
  const res = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });

  if (!res.ok) throw new Error("Refresh failed");

  const data = await res.json();
  updateToken(data.access_token);
  return data.access_token;
}

/**
 * Обертка над fetch с автоматическим обновлением токена при 401.
 * При невозможности обновить — очищает access_token и перенаправляет на /login.
 * refresh_token передаётся браузером автоматически через httpOnly cookie.
 */
export async function apiFetch(path, token, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  let res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
    credentials: "include", // отправляем httpOnly cookie с каждым запросом
  });

  if (res.status !== 401) return res;

  // --- 401: пробуем обновить токен ---
  if (isRefreshing) {
    return new Promise((resolve) => {
      addRefreshSubscriber(async (newToken) => {
        const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
        resolve(fetch(`${BASE}${path}`, { ...options, headers: retryHeaders, credentials: "include" }));
      });
    });
  }

  isRefreshing = true;

  try {
    const newToken = await tryRefresh();
    isRefreshing = false;
    onTokenRefreshed(newToken);

    const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
    return fetch(`${BASE}${path}`, { ...options, headers: retryHeaders, credentials: "include" });
  } catch {
    isRefreshing = false;
    updateToken(null);
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Сессия истекла. Перенаправление на страницу входа.");
  }
}
