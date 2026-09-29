import { updateToken, getToken } from "@/lib/tokenBus";

const raw =
  process.env.NEXT_PUBLIC_API_URL !== undefined
    ? process.env.NEXT_PUBLIC_API_URL
    : (process.env.NEXT_PUBLIC_ENDPOINT ?? (typeof window === "undefined" ? "http://backend:8000" : ""));

export const API_ROOT = raw
  ? raw.replace(/\/api\/v1\/?$/, "").replace(/\/+$/, "")
  : "";

export const API_BASE = !raw
  ? "/api/v1"
  : raw.endsWith("/api/v1")
  ? raw.replace(/\/+$/, "")
  : `${raw.replace(/\/+$/, "")}/api/v1`;

let refreshPromise = null;

export function refreshSession() {
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
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
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  // Root endpoints (like /ready, /health) are served on API_ROOT
  const isRootEndpoint =
    normalizedPath === "/ready" ||
    normalizedPath === "/health" ||
    normalizedPath === "/docs" ||
    normalizedPath === "/openapi.json";
  const url = `${isRootEndpoint ? API_ROOT : API_BASE}${normalizedPath}`;

  let res = await fetch(url, {
    ...options,
    headers,
    credentials: "include", // отправляем httpOnly cookie с каждым запросом
  });

  if (res.status !== 401) return res;

  // --- 401: пробуем обновить токен ---
  try {
    const newToken = await refreshSession();
    const retryHeaders = { ...headers, Authorization: `Bearer ${newToken}` };
    const retryRes = await fetch(url, {
      ...options,
      headers: retryHeaders,
      credentials: "include",
    });
    if (retryRes.status === 401) {
      updateToken(null);
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.href = "/login";
      }
      throw new Error("Сессия истекла. Перенаправление на страницу входа.");
    }
    return retryRes;
  } catch (error) {
    updateToken(null);
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
    throw new Error("Сессия истекла. Перенаправление на страницу входа.");
  }
}
