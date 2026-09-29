import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const GEOAPIFY_KEY =
  process.env.GEOAPIFY_API_KEY ||
  process.env.NEXT_PUBLIC_GEOAPIFY_API_KEY ||
  "6178ae85cca24dc1a0f4bc5ae3a8d7bb";

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

// Local cache lookup
function findInLocalCache(districtName) {
  if (!districtName) return null;
  const clean = districtName.trim().toLowerCase();
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

  // 1. Попытка получить границу через Geoapify Boundaries API по координатам
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    try {
      const geoapifyUrl = `https://api.geoapify.com/v1/boundaries/part-of?lat=${lat}&lon=${lon}&geometry=geometry_1000&apiKey=${GEOAPIFY_KEY}`;
      const res = await fetch(geoapifyUrl, { next: { revalidate: 3600 } });
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
    } catch (err) {
      console.error("Geoapify boundaries fetch error:", err);
    }
  }

  // 2. Поиск в локальном кэше подготовленных реальных полигонов районов
  const localMatch = findInLocalCache(district);
  if (localMatch) {
    return NextResponse.json({
      success: true,
      source: "local-cache",
      ...localMatch,
    });
  }

  // 3. Поиск через Geoapify (Geocoding -> Boundaries API)
  if (district && GEOAPIFY_KEY) {
    try {
      const q = [district, city].filter(Boolean).join(", ");
      const geocodeUrl = `https://api.geoapify.com/v1/geocode/search?text=${encodeURIComponent(q)}&format=geojson&apiKey=${GEOAPIFY_KEY}`;
      const geoRes = await fetch(geocodeUrl, { next: { revalidate: 3600 } });
      if (geoRes.ok) {
        const geoData = await geoRes.json();
        const pt = geoData.features?.[0]?.properties;
        if (pt && Number.isFinite(pt.lat) && Number.isFinite(pt.lon)) {
          const boundaryUrl = `https://api.geoapify.com/v1/boundaries/part-of?lat=${pt.lat}&lon=${pt.lon}&geometry=geometry_1000&apiKey=${GEOAPIFY_KEY}`;
          const bRes = await fetch(boundaryUrl, { next: { revalidate: 3600 } });
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
    } catch (err) {
      console.error("Geoapify search error:", err);
    }
  }

  // 4. Fallback: поиск полигона через Nominatim
  if (district) {
    try {
      const q = [district, city].filter(Boolean).join(", ");
      const nominatimUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=geojson&polygon_geojson=1`;
      const res = await fetch(nominatimUrl, {
        headers: { "User-Agent": "BeelineBusinessApp/1.0" },
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
    } catch (err) {
      console.error("Nominatim search error:", err);
    }
  }

  return NextResponse.json(
    { success: false, message: "Real administrative boundary not found" },
    { status: 404 }
  );
}
