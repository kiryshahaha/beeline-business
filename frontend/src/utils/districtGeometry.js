/**
 * Utility for real administrative district boundaries and point-in-polygon checks.
 * Uses Geoapify Boundaries API and official OpenStreetMap polygons.
 * NO artificial radius or circle approximations.
 */

/**
 * Checks if a point [longitude, latitude] is inside a GeoJSON Polygon or MultiPolygon.
 * Uses the ray-casting algorithm.
 * @param {[number, number]} point - [lng, lat]
 * @param {Object} geometry - GeoJSON Polygon or MultiPolygon
 * @returns {boolean}
 */
export function isPointInPolygon(point, geometry) {
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
      // Check interior holes if any
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

/**
 * Calculates bounding box [[minLng, minLat], [maxLng, maxLat]] for GeoJSON geometry.
 */
export function calculateGeometryBounds(geometry) {
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

import kuzminki from "@/data/districtBoundaries/kuzminki.json";
import biryulyovo from "@/data/districtBoundaries/biryulyovo.json";
import nagorny from "@/data/districtBoundaries/nagorny.json";
import tsao from "@/data/districtBoundaries/tsao.json";
import sao from "@/data/districtBoundaries/sao.json";
import svao from "@/data/districtBoundaries/svao.json";
import vao from "@/data/districtBoundaries/vao.json";
import yuvao from "@/data/districtBoundaries/yuvao.json";
import yuao from "@/data/districtBoundaries/yuao.json";
import yuzao from "@/data/districtBoundaries/yuzao.json";
import zao from "@/data/districtBoundaries/zao.json";
import szao from "@/data/districtBoundaries/szao.json";
import zelao from "@/data/districtBoundaries/zelao.json";
import nao from "@/data/districtBoundaries/nao.json";
import tao from "@/data/districtBoundaries/tao.json";

const MOSCOW_GEO_DISTRICTS = [kuzminki, biryulyovo, nagorny];
const MOSCOW_GEO_OKRUGS = [
  tsao, sao, svao, vao, yuvao, yuao, yuzao, zao, szao, zelao, nao, tao,
];

/**
 * Finds the specific Moscow district name for a given point [longitude, latitude].
 */
export function findDistrictByCoordinates(lon, lat) {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  // Check specific district polygons first
  for (const item of MOSCOW_GEO_DISTRICTS) {
    if (isPointInPolygon([lon, lat], item.geometry)) {
      return item.districtName;
    }
  }
  // Then check okrug polygons
  for (const item of MOSCOW_GEO_OKRUGS) {
    if (isPointInPolygon([lon, lat], item.geometry)) {
      return item.districtName;
    }
  }
  return null;
}

/**
 * Finds the containing Moscow administrative okrug for a given point [longitude, latitude].
 */
export function findOkrugByCoordinates(lon, lat) {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  for (const item of MOSCOW_GEO_OKRUGS) {
    if (isPointInPolygon([lon, lat], item.geometry)) {
      return item.districtName;
    }
  }
  return null;
}

/**
 * Searches local cache by district or okrug name/alias.
 */
export function findLocalDistrictByName(districtName) {
  if (!districtName) return null;
  const clean = districtName.trim().toLowerCase();
  if (clean === "не указан" || clean === "адрес не указан") return null;

  const all = [...MOSCOW_GEO_DISTRICTS, ...MOSCOW_GEO_OKRUGS];
  for (const item of all) {
    const itemName = (item.districtName || "").toLowerCase();
    const aliases = (item.aliases || []).map((a) => a.toLowerCase());
    if (itemName === clean || aliases.includes(clean)) {
      return {
        districtName: item.districtName,
        displayName: item.displayName,
        featureCollection: {
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: item.geometry,
              properties: {
                name: item.districtName,
                displayName: item.displayName,
              },
            },
          ],
        },
        geometry: item.geometry,
        bounds: calculateGeometryBounds(item.geometry),
      };
    }
  }
  return null;
}

const boundaryCache = new Map();

/**
 * Fetches real administrative boundary GeoJSON from our Next.js API (powered by Geoapify + OSM cache).
 * @param {{ district?: string, city?: string, lat?: number, lon?: number }} params
 * @returns {Promise<{ districtName: string, featureCollection: Object, bounds: [[number, number], [number, number]] } | null>}
 */
export async function fetchRealDistrictBoundary({ district, city, lat, lon }) {
  const cacheKey = `${(district || "").toLowerCase()}_${(city || "").toLowerCase()}_${lat || ""}_${lon || ""}`;
  if (boundaryCache.has(cacheKey)) {
    return boundaryCache.get(cacheKey);
  }

  // 1. Быстрый синхронный локальный поиск по названию
  const isInvalidName =
    !district ||
    district.trim().toLowerCase() === "не указан" ||
    district.trim().toLowerCase() === "адрес не указан";

  if (!isInvalidName) {
    const localMatch = findLocalDistrictByName(district);
    if (localMatch) {
      boundaryCache.set(cacheKey, localMatch);
      return localMatch;
    }
  }

  // 2. Быстрый синхронный локальный поиск по координатам
  if (Number.isFinite(lon) && Number.isFinite(lat)) {
    // Check specific district first
    for (const item of [...MOSCOW_GEO_DISTRICTS, ...MOSCOW_GEO_OKRUGS]) {
      if (isPointInPolygon([lon, lat], item.geometry)) {
        const result = {
          districtName: item.districtName,
          displayName: item.displayName,
          featureCollection: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: item.geometry,
                properties: {
                  name: item.districtName,
                  displayName: item.displayName,
                },
              },
            ],
          },
          geometry: item.geometry,
          bounds: calculateGeometryBounds(item.geometry),
        };
        boundaryCache.set(cacheKey, result);
        return result;
      }
    }
  }

  // 3. Обращение к API эндпоинту
  const queryParams = new URLSearchParams();
  if (district && !isInvalidName) queryParams.set("district", district);
  if (city) queryParams.set("city", city);
  if (lat != null && Number.isFinite(lat)) queryParams.set("lat", String(lat));
  if (lon != null && Number.isFinite(lon)) queryParams.set("lon", String(lon));

  try {
    const res = await fetch(`/api/district-boundary?${queryParams.toString()}`);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.success || !data.feature) return null;

    const feature = data.feature;
    const bounds = data.bounds || calculateGeometryBounds(feature.geometry);

    const result = {
      districtName: data.districtName || district,
      displayName: data.displayName || data.districtName,
      featureCollection: {
        type: "FeatureCollection",
        features: [feature],
      },
      geometry: feature.geometry,
      bounds,
    };

    boundaryCache.set(cacheKey, result);
    return result;
  } catch (err) {
    console.error("fetchRealDistrictBoundary error:", err);
    return null;
  }
}

