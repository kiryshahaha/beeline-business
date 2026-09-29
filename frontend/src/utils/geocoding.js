/**
 * Geocoding and Reverse Geocoding helpers via MapTiler API with Geoapify fallback.
 */

const MAPTILER_KEY = process.env.NEXT_PUBLIC_MAPTILER_API_KEY || "GgqQJqVNCH4XkEWcVnJs";

/**
 * Парсит компоненты адреса из ответа MapTiler feature
 */
export function parseMapTilerFeature(feature) {
  if (!feature) return null;

  const [lng, lat] = feature.center || [0, 0];
  const placeName = feature.place_name_ru || feature.place_name || "";
  const text = feature.text_ru || feature.text || "";
  const houseNumber = feature.address || "";

  // Контекст (район, город, округ)
  let city = "Москва";
  let district = "";
  let street = text;

  if (feature.context && Array.isArray(feature.context)) {
    feature.context.forEach((ctx) => {
      const id = ctx.id || "";
      const ctxText = ctx.text_ru || ctx.text || "";
      if (id.startsWith("municipality") || id.startsWith("subdistrict") || id.startsWith("district")) {
        district = ctxText.replace(/ район| муниципальный округ/gi, "");
      } else if (id.startsWith("place") || id.startsWith("city")) {
        city = ctxText;
      }
    });
  }

  // Если номер дома не отделен, пробуем извлечь из текста или placeName
  let buildingNumber = houseNumber;
  if (!buildingNumber) {
    const match = placeName.match(/(\d+[\wа-яА-Я/-]*)/);
    if (match) {
      buildingNumber = match[1];
    }
  }

  return {
    formattedAddress: placeName,
    street: street || text,
    buildingNumber: buildingNumber || "1",
    district: district || "Центральный",
    city: city || "Москва",
    lat,
    lng,
  };
}

/**
 * Быстрый поиск адресов (автокомплит)
 */
export async function searchAddressSuggestions(query) {
  if (!query || query.trim().length < 2) return [];

  // Добавляем "Москва" для локализации, если не указано
  const trimmed = query.trim();
  const searchQuery = /москва/i.test(trimmed) ? trimmed : `Москва, ${trimmed}`;

  try {
    const url = `https://api.maptiler.com/geocoding/${encodeURIComponent(searchQuery)}.json?key=${MAPTILER_KEY}&language=ru&limit=6&proximity=37.6173,55.7558`;
    const res = await fetch(url);
    if (!res.ok) return [];

    const data = await res.json();
    const features = data.features || [];

    return features.map((f) => {
      const parsed = parseMapTilerFeature(f);
      return {
        id: f.id,
        label: f.place_name_ru || f.place_name || parsed.formattedAddress,
        parsed,
      };
    });
  } catch (err) {
    console.warn("Geocoding search failed:", err);
    return [];
  }
}

/**
 * Обратное геокодирование по клику на карте (Reverse Geocoding)
 */
export async function reverseGeocodeCoordinates(lat, lng) {
  try {
    const url = `https://api.maptiler.com/geocoding/${lng},${lat}.json?key=${MAPTILER_KEY}&language=ru`;
    const res = await fetch(url);
    if (!res.ok) return null;

    const data = await res.json();
    const features = data.features || [];
    if (features.length === 0) return null;

    // Берем наиболее точную деталь (обычно первая)
    const bestFeature = features[0];
    return parseMapTilerFeature(bestFeature);
  } catch (err) {
    console.warn("Reverse geocode failed:", err);
    return null;
  }
}
