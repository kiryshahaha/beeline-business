import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const GEOAPIFY_KEY =
  process.env.GEOAPIFY_API_KEY ||
  process.env.NEXT_PUBLIC_GEOAPIFY_API_KEY ||
  "";

function calculateBounds(geometry) {
  if (!geometry || !geometry.coordinates) return null;

  let minLng = Infinity;
  let minLat = Infinity;
  let maxLng = -Infinity;
  let maxLat = -Infinity;

  function traverse(coords) {
    if (
      Array.isArray(coords) &&
      coords.length >= 2 &&
      typeof coords[0] === "number" &&
      typeof coords[1] === "number"
    ) {
      const [lng, lat] = coords;
      if (Number.isFinite(lng) && Number.isFinite(lat)) {
        if (lng < minLng) minLng = lng;
        if (lng > maxLng) maxLng = lng;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      }
      return;
    }
    if (Array.isArray(coords)) {
      coords.forEach(traverse);
    }
  }

  traverse(geometry.coordinates);

  if (!Number.isFinite(minLng) || !Number.isFinite(minLat)) return null;
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}

function isPointInPolygon(point, geometry) {
  if (!point || !geometry) return false;
  const [x, y] = point;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false;

  const polygons =
    geometry.type === "MultiPolygon"
      ? geometry.coordinates
      : geometry.type === "Polygon"
        ? [geometry.coordinates]
        : [];

  for (const rings of polygons) {
    if (!rings || !rings.length) continue;
    const outerRing = rings[0];
    if (!outerRing || outerRing.length < 3) continue;

    let inside = false;
    for (let i = 0, j = outerRing.length - 1; i < outerRing.length; j = i++) {
      const xi = outerRing[i][0];
      const yi = outerRing[i][1];
      const xj = outerRing[j][0];
      const yj = outerRing[j][1];

      const intersect =
        yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
      if (intersect) inside = !inside;
    }

    if (inside) {
      let inHole = false;
      for (let h = 1; h < rings.length; h++) {
        const hole = rings[h];
        let holeInside = false;
        for (let i = 0, j = hole.length - 1; i < hole.length; j = i++) {
          const xi = hole[i][0];
          const yi = hole[i][1];
          const xj = hole[j][0];
          const yj = hole[j][1];

          const intersect =
            yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
          if (intersect) holeInside = !holeInside;
        }
        if (holeInside) {
          inHole = true;
          break;
        }
      }
      if (!inHole) return true;
    }
  }

  return false;
}

// Local cache lookup by coordinates (Point-in-Polygon against real Moscow boundaries)
function findInLocalCacheByCoordinates(lon, lat) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const dir = path.join(process.cwd(), "src/data/districtBoundaries");
  if (!fs.existsSync(dir)) return null;

  const files = fs.readdirSync(dir);
  let districtMatch = null;
  let okrugMatch = null;

  for (const file of files) {
    if (!file.endsWith(".json")) continue;
    try {
      const raw = fs.readFileSync(path.join(dir, file), "utf-8");
      const data = JSON.parse(raw);
      if (isPointInPolygon([lon, lat], data.geometry)) {
        const name = (data.districtName || "").toLowerCase();
        const isOkrug = name.includes("округ") || name.includes("ао");
        if (!isOkrug && !districtMatch) {
          districtMatch = data;
        } else if (isOkrug && !okrugMatch) {
          okrugMatch = data;
        }
      }
    } catch {
      // ignore
    }
  }

  const bestMatch = districtMatch || okrugMatch;
  if (bestMatch) {
    const feature = {
      type: "Feature",
      geometry: bestMatch.geometry,
      properties: {
        name: bestMatch.districtName,
        displayName: bestMatch.displayName,
      },
    };
    const bounds = calculateBounds(bestMatch.geometry);
    return {
      districtName: bestMatch.districtName,
      displayName: bestMatch.displayName,
      feature,
      bounds,
    };
  }

  return null;
}

const DISTRICT_TO_OKRUG = {
  "академический": "Юго-Западный административный округ",
  "гагаринский": "Юго-Западный административный округ",
  "зюзино": "Юго-Западный административный округ",
  "котловка": "Юго-Западный административный округ",
  "ломоносовский": "Юго-Западный административный округ",
  "обручевский": "Юго-Западный административный округ",
  "теrelationship": "Юго-Западный административный округ",
  "басманный": "Центральный административный округ",
  "таганский": "Центральный административный округ",
  "хамовники": "Центральный административный округ",
  "замоскворечье": "Центральный административный округ",
  "арбат": "Центральный административный округ",
  "тверской": "Центральный административный округ",
  "выхино": "Юго-Восточный административный округ",
  "выхино-жулебино": "Юго-Восточный административный округ",
  "рязанский": "Юго-Восточный административный округ",
  "текстильщики": "Юго-Восточный административный округ",
  "лефортово": "Юго-Восточный административный округ",
  "нижегородский": "Юго-Восточный административный округ",
  "южнопортовый": "Юго-Восточный административный округ",
  "печатники": "Юго-Восточный административный округ",
  "люблино": "Юго-Восточный административный округ",
  "марьино": "Юго-Восточный административный округ",
  "капотня": "Юго-Восточный административный округ",
  "даниловский": "Южный административный округ",
  "gpon даниловский": "Южный административный округ",
  "донской": "Южный административный округ",
  "нагатино - садовники": "Южный административный округ",
  "нагатинский затон": "Южный административный округ",
  "москворечье - сабурово": "Южный административный округ",
  "царицыно": "Южный административный округ",
  "бирюлево восточное": "Южный административный округ",
  "бирюлево западное": "Южный административный округ",
  "орехово борисово северное": "Южный административный округ",
  "орехово борисово южное": "Южный административный округ",
  "братеево": "Южный административный округ",
  "зябликово": "Южный административный округ",
  "чертаново северное": "Южный административный округ",
  "чертаново центральное": "Южный административный округ",
  "чертаново южное": "Южный административный округ",
  "сокольники": "Восточный административный округ",
  "перово": "Восточный административный округ",
  "новогиреево": "Восточный административный округ",
  "измайлово": "Восточный административный округ",
  "гольяново": "Восточный административный округ",
  "преображенское": "Восточный административный округ",
};

// Local cache lookup
function findInLocalCache(districtName) {
  if (!districtName) return null;
  const clean = districtName.trim().toLowerCase();
  if (clean === "не указан" || clean === "адрес не указан") return null;
  const dir = path.join(process.cwd(), "src/data/districtBoundaries");

  if (!fs.existsSync(dir)) return null;

  const files = fs.readdirSync(dir);
  let bestMatch = null;
  let bestScore = 0; // 3: exact name, 2: exact alias, 1: substring

  for (const file of files) {
    if (!file.endsWith(".json")) continue;
    try {
      const raw = fs.readFileSync(path.join(dir, file), "utf-8");
      const data = JSON.parse(raw);
      const name = (data.districtName || "").toLowerCase();
      const aliases = (data.aliases || []).map((a) => a.toLowerCase());

      if (name === clean) {
        bestMatch = data;
        bestScore = 3;
        break;
      }
      if (aliases.includes(clean)) {
        if (bestScore < 2) {
          bestMatch = data;
          bestScore = 2;
        }
      } else if (name.includes(clean) || aliases.some((a) => a.includes(clean) || clean.includes(a))) {
        if (bestScore < 1) {
          bestMatch = data;
          bestScore = 1;
        }
      }
    } catch {
      // ignore read error
    }
  }

  // Fallback to containing okrug if the district is in Moscow
  if (!bestMatch && DISTRICT_TO_OKRUG[clean]) {
    const okrugTarget = DISTRICT_TO_OKRUG[clean].toLowerCase();
    for (const file of files) {
      if (!file.endsWith(".json")) continue;
      try {
        const raw = fs.readFileSync(path.join(dir, file), "utf-8");
        const data = JSON.parse(raw);
        const name = (data.districtName || "").toLowerCase();
        if (name === okrugTarget) {
          bestMatch = {
            ...data,
            districtName: districtName,
            displayName: `${districtName} (${data.districtName})`,
          };
          break;
        }
      } catch {}
    }
  }

  if (bestMatch) {
    const feature = {
      type: "Feature",
      geometry: bestMatch.geometry,
      properties: {
        name: bestMatch.districtName,
        displayName: bestMatch.displayName,
      },
    };
    const bounds = calculateBounds(bestMatch.geometry);
    return {
      districtName: bestMatch.districtName,
      displayName: bestMatch.displayName,
      feature,
      bounds,
    };
  }

  return null;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const district = searchParams.get("district");
  const city = searchParams.get("city");
  const latStr = searchParams.get("lat");
  const lonStr = searchParams.get("lon");

  const lat = latStr ? parseFloat(latStr) : null;
  const lon = lonStr ? parseFloat(lonStr) : null;

  const isInvalidDistrict =
    !district ||
    district.trim().toLowerCase() === "не указан" ||
    district.trim().toLowerCase() === "адрес не указан";

  // 1. Приоритетный поиск в локальном кэше подготовленных реальных полигонов (0ms задержка, без сети)
  if (!isInvalidDistrict) {
    const localMatch = findInLocalCache(district);
    if (localMatch) {
      return NextResponse.json({
        success: true,
        source: "local-cache",
        ...localMatch,
      });
    }
  }

  // 2. Приоритетный поиск в локальном кэше по координатам (Point-in-Polygon, 0ms задержка, без сети)
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    const coordMatch = findInLocalCacheByCoordinates(lon, lat);
    if (coordMatch) {
      return NextResponse.json({
        success: true,
        source: "local-cache-point-in-polygon",
        ...coordMatch,
      });
    }
  }

  // 2. Попытка получить границу через Geoapify Boundaries API по координатам
  if (Number.isFinite(lat) && Number.isFinite(lon) && GEOAPIFY_KEY) {
    try {
      const geoapifyUrl = `https://api.geoapify.com/v1/boundaries/part-of?lat=${lat}&lon=${lon}&geometry=geometry_1000&apiKey=${GEOAPIFY_KEY}`;
      const res = await fetch(geoapifyUrl, {
        signal: AbortSignal.timeout(2500),
        next: { revalidate: 3600 },
      });
      if (res.ok) {
        const data = await res.json();
        const features = data.features || [];

        const isMoscow =
          (city && city.toLowerCase().includes("москв")) ||
          features.some((f) => (f.properties?.name || "").toLowerCase() === "москва") ||
          (lat >= 55.1 && lat <= 56.1 && lon >= 36.8 && lon <= 38.3);

        let matched = null;

        // Если передано желаемое название района, ищем совпадение
        if (district) {
          const cleanTarget = district.toLowerCase().replace(/район|административный|округ/g, "").trim();
          matched = features.find((f) => {
            const n = (f.properties?.name || "").toLowerCase();
            return (
              (n.includes(cleanTarget) || cleanTarget.includes(n)) &&
              (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            );
          });
        }

        // Если не найдено по названию:
        // В Москве выбираем Административный округ (АО)
        if (!matched && isMoscow) {
          matched =
            features.find(
              (f) =>
                f.properties?.name?.toLowerCase().includes("административный округ") &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            ) ||
            features.find(
              (f) =>
                f.properties?.categories?.includes("administrative.state_level") &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            ) ||
            features.find(
              (f) =>
                f.properties?.name?.toLowerCase().includes("округ") &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            );
        }

        // Вне Москвы выбираем административный район
        if (!matched) {
          matched =
            features.find(
              (f) =>
                f.properties?.name?.toLowerCase().includes("район") &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            ) ||
            features.find(
              (f) =>
                f.properties?.categories?.includes("administrative.district_level") &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            ) ||
            features.find(
              (f) =>
                f.properties?.categories?.includes("administrative.state_level") &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
            );
        }

        if (matched?.geometry) {
          const bounds = calculateBounds(matched.geometry);
          return NextResponse.json({
            success: true,
            source: "geoapify",
            districtName: matched.properties?.name || district,
            displayName: matched.properties?.formatted || matched.properties?.name,
            feature: matched,
            bounds,
          });
        }
      }
    } catch {
      // Игнорируем сетевые сбои внешнего API
    }
  }

  // 3. Поиск через Geoapify (Geocoding -> Boundaries API)
  if (district && GEOAPIFY_KEY) {
    try {
      const q = [district, city].filter(Boolean).join(", ");
      const geocodeUrl = `https://api.geoapify.com/v1/geocode/search?text=${encodeURIComponent(q)}&format=geojson&apiKey=${GEOAPIFY_KEY}`;
      const geoRes = await fetch(geocodeUrl, {
        signal: AbortSignal.timeout(2500),
        next: { revalidate: 3600 },
      });
      if (geoRes.ok) {
        const geoData = await geoRes.json();
        const pt = geoData.features?.[0]?.properties;
        if (pt && Number.isFinite(pt.lat) && Number.isFinite(pt.lon)) {
          const boundaryUrl = `https://api.geoapify.com/v1/boundaries/part-of?lat=${pt.lat}&lon=${pt.lon}&geometry=geometry_1000&apiKey=${GEOAPIFY_KEY}`;
          const bRes = await fetch(boundaryUrl, {
            signal: AbortSignal.timeout(2500),
            next: { revalidate: 3600 },
          });
          if (bRes.ok) {
            const bData = await bRes.json();
            const cleanTarget = district.toLowerCase().replace(/район|округ/g, "").trim();
            const bFeatures = bData.features || [];

            let matched = bFeatures.find((f) => {
              const n = (f.properties?.name || "").toLowerCase();
              return (
                (n.includes(cleanTarget) || cleanTarget.includes(n)) &&
                (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
              );
            });

            if (!matched) {
              matched =
                bFeatures.find(
                  (f) =>
                    f.properties?.name?.toLowerCase().includes("район") &&
                    (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
                ) ||
                bFeatures.find(
                  (f) =>
                    f.properties?.categories?.includes("administrative.state_level") &&
                    (f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon")
                );
            }

            if (matched?.geometry) {
              const bounds = calculateBounds(matched.geometry);
              return NextResponse.json({
                success: true,
                source: "geoapify",
                districtName: matched.properties?.name || district,
                displayName: matched.properties?.formatted || matched.properties?.name,
                feature: matched,
                bounds,
              });
            }
          }
        }
      }
    } catch {
      // Игнорируем сетевые ошибки Geoapify
    }
  }

  // 4. Fallback: поиск полигона через Nominatim
  if (district) {
    try {
      const q = [district, city].filter(Boolean).join(", ");
      const nominatimUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=geojson&polygon_geojson=1`;
      const res = await fetch(nominatimUrl, {
        headers: { "User-Agent": "BeelineBusinessApp/1.0" },
        signal: AbortSignal.timeout(3000),
        next: { revalidate: 3600 },
      });
      if (res.ok) {
        const data = await res.json();
        const feat = data.features?.find(
          (f) => f.geometry?.type === "Polygon" || f.geometry?.type === "MultiPolygon"
        );
        if (feat) {
          const bounds = calculateBounds(feat.geometry);
          return NextResponse.json({
            success: true,
            source: "nominatim",
            districtName: feat.properties?.name || district,
            displayName: feat.properties?.display_name,
            feature: feat,
            bounds,
          });
        }
      }
    } catch {
      // Игнорируем сетевые ошибки внешних сервисов
    }
  }

  return NextResponse.json(
    { success: false, message: "Real administrative boundary not found" },
    { status: 404 }
  );
}
