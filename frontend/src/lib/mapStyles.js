// frontend/src/lib/mapStyles.js

export const MAPTILER_KEY =
  process.env.NEXT_PUBLIC_MAPTILER_API_KEY || "GgqQJqVNCH4XkEWcVnJs";

export const MAP_THEME_STORAGE_KEY = "beeline_map_theme";
export const LEGACY_STORAGE_KEY = "beeline_map_style";

export const DEFAULT_MAP_THEME = "standard";

export const MAP_STYLES = {
  standard: {
    id: "standard",
    label: "Обычная",
    url: `https://api.maptiler.com/maps/01a0a53f-a24b-7778-b5e1-b59ba3d6f612/style.json?key=${MAPTILER_KEY}`,
  },
  satellite: {
    id: "satellite",
    label: "Спутник",
    url: `https://api.maptiler.com/maps/019fce77-aa22-7f7d-923a-691e2491e4dd/style.json?key=${MAPTILER_KEY}`,
  },
  dark: {
    id: "dark",
    label: "Тёмная",
    url: `https://api.maptiler.com/maps/01a0620c-e3b1-7d64-b992-a04cd0fb9fdc/style.json?key=${MAPTILER_KEY}`,
  },
};

/**
 * Returns saved map theme from localStorage or default
 */
export function getSavedMapTheme() {
  if (typeof window === "undefined") {
    return DEFAULT_MAP_THEME;
  }
  try {
    const saved =
      localStorage.getItem(MAP_THEME_STORAGE_KEY) ||
      localStorage.getItem(LEGACY_STORAGE_KEY);
    if (saved && MAP_STYLES[saved]) {
      return saved;
    }
  } catch {}
  return DEFAULT_MAP_THEME;
}

/**
 * Persists chosen map theme into localStorage and emits sync event
 */
export function saveMapTheme(themeId) {
  if (typeof window === "undefined") return;
  if (!MAP_STYLES[themeId]) return;
  try {
    localStorage.setItem(MAP_THEME_STORAGE_KEY, themeId);
    window.dispatchEvent(
      new CustomEvent("beeline_map_theme_changed", { detail: themeId })
    );
  } catch {}
}

/**
 * Returns style JSON URL for a given theme id
 */
export function getMapStyleUrl(themeId) {
  const item = MAP_STYLES[themeId] || MAP_STYLES[DEFAULT_MAP_THEME];
  return item.url;
}
