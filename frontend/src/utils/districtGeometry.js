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

  const queryParams = new URLSearchParams();
  if (district) queryParams.set("district", district);
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
