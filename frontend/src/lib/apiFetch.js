import { updateToken, getToken } from "@/lib/tokenBus";

const BASE = process.env.NEXT_PUBLIC_ENDPOINT;

let refreshPromise = null;

export function refreshSession() {
  if (refreshPromise) return refreshPromise;
  
  refreshPromise = (async () => {
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) throw new Error("Refresh failed");
      const data = await res.json();
      updateToken(data.access_token);
      return data.access_token;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Обертка над fetch с автоматическим обновлением токена при 401.
 * При невозможности обновить — очищает access_token и перенаправляет на /login.
 * refresh_token передаётся браузером автоматически через httpOnly cookie.
 *
 * @param {string} path — путь API (например "/tickets")
 * @param {object} [options] — стандартные опции fetch (method, body, headers и т.д.)
 */
export async function apiFetch(path, options = {}) {
  const token = getToken();
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
  try {
    const newToken = await refreshSession();
    const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
    return fetch(`${BASE}${path}`, { ...options, headers: retryHeaders, credentials: "include" });
  } catch (error) {
    updateToken(null);
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new Error("Сессия истекла. Перенаправление на страницу входа.");
  }
}
