import json
import math
import os

from config import settings
from db.redis_store import get_property_info_map
from utils.retry import http_post, http_get
from core.log import get_logger

logger = get_logger("tools.landmarks")

# ---------------------------------------------------------------------------
# Transit line data (loaded once)
# ---------------------------------------------------------------------------
_TRANSIT_DATA: dict | None = None


def _load_transit_data() -> dict:
    global _TRANSIT_DATA
    if _TRANSIT_DATA is not None:
        return _TRANSIT_DATA
    try:
        path = os.path.join(os.path.dirname(__file__), "..", "..", "data", "transit_lines.json")
        with open(path, "r") as f:
            _TRANSIT_DATA = json.load(f)
    except Exception:
        _TRANSIT_DATA = {}
    return _TRANSIT_DATA


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    rlat1, rlon1, rlat2, rlon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _walk_minutes(distance_km: float) -> float:
    """Estimate walking time at ~5 km/h."""
    return (distance_km / 5.0) * 60


# ---------------------------------------------------------------------------
# Overpass: find nearest metro / railway station
# ---------------------------------------------------------------------------
async def _find_nearest_station(lat: float, lon: float, radius: int = 2000) -> list[dict]:
    """Query Overpass API for metro/railway stations near a point."""
    query = f"""
    [out:json];
    (
      node["railway"="station"](around:{radius},{lat},{lon});
      node["station"="subway"](around:{radius},{lat},{lon});
      node["railway"="halt"](around:{radius},{lat},{lon});
    );
    out body 5;
    """
    try:
        data = await http_get(
            "https://overpass-api.de/api/interpreter",
            params={"data": query},
            timeout=15,
        )
    except Exception as e:
        logger.warning("Overpass station query failed: %s", e)
        return []

    results = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name", "")
        if not name:
            continue
        st_lat = el.get("lat", 0)
        st_lon = el.get("lon", 0)
        dist = _haversine_km(lat, lon, st_lat, st_lon)
        results.append({
            "name": name,
            "lat": st_lat,
            "lon": st_lon,
            "distance_km": round(dist, 2),
            "walk_min": round(_walk_minutes(dist), 0),
            "type": tags.get("railway", tags.get("station", "station")),
        })
    results.sort(key=lambda x: x["distance_km"])
    return results


# ---------------------------------------------------------------------------
# Transit time estimation via transit_lines.json
# ---------------------------------------------------------------------------
def _find_station_on_line(station_name: str, city: str) -> list[dict]:
    """Find which transit lines a station belongs to."""
    data = _load_transit_data()
    city_data = data.get(city.lower(), {})
    station_lower = station_name.strip().lower()
    matches = []
    for mode in ("metro", "rail"):
        for line in city_data.get(mode, []):
            for idx, s in enumerate(line["stations"]):
                if station_lower in s.lower() or s.lower() in station_lower:
                    matches.append({
                        "line_name": line["name"],
                        "station_index": idx,
                        "avg_speed_kmh": line["avg_speed_kmh"],
                        "total_stations": len(line["stations"]),
                        "mode": mode,
                    })
    return matches


def _estimate_transit_time(
    origin_station: str, dest_station: str, city: str
) -> dict | None:
    """Estimate transit time between two stations if they share a line."""
    origin_lines = _find_station_on_line(origin_station, city)
    dest_lines = _find_station_on_line(dest_station, city)

    for ol in origin_lines:
        for dl in dest_lines:
            if ol["line_name"] == dl["line_name"]:
                station_gap = abs(ol["station_index"] - dl["station_index"])
                # Approx 1.5 km between stations for metro, 2.5 km for rail
                inter_station_km = 1.5 if ol["mode"] == "metro" else 2.5
                distance_km = station_gap * inter_station_km
                travel_min = (distance_km / ol["avg_speed_kmh"]) * 60
                return {
                    "line": ol["line_name"],
                    "stations": station_gap,
                    "travel_min": round(travel_min, 0),
                    "mode": ol["mode"],
                }
    return None


# ---------------------------------------------------------------------------
# Helper: resolve property from info_map
# ---------------------------------------------------------------------------
def _find_prop(user_id: str, property_name: str) -> dict | None:
    info_map = get_property_info_map(user_id)
    for p in info_map:
        if property_name.strip().lower() in p.get("property_name", "").strip().lower():
            return p
    return None


# ---------------------------------------------------------------------------
# Tool: fetch_landmarks (original — distance by car)
# ---------------------------------------------------------------------------
async def fetch_landmarks(user_id: str, landmark_name: str, property_name: str, **kwargs) -> str:
    prop = _find_prop(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    prop_lat = prop.get("property_lat", "")
    prop_long = prop.get("property_long", "")
    if not prop_lat or not prop_long:
        return "Property coordinates not available."

    try:
        geo_data = await http_post(
            f"{settings.RENTOK_API_BASE_URL}/property/getLatLongProperty",
            json={"address": landmark_name},
        )
    except Exception as e:
        return f"Error finding landmark: {str(e)}"

    landmark_lat = geo_data.get("lat", geo_data.get("latitude", ""))
    landmark_long = geo_data.get("long", geo_data.get("longitude", ""))
    if not landmark_lat or not landmark_long:
        return f"Could not find coordinates for '{landmark_name}'."

    try:
        dist_data = await http_get(
            f"http://maps.rentok.com/table/v1/driving/{prop_long},{prop_lat};{landmark_long},{landmark_lat}",
            params={"sources": "0", "api_key": settings.OSRM_API_KEY},
        )
    except Exception as e:
        return f"Error calculating distance: {str(e)}"

    durations = dist_data.get("durations", [[]])
    distances = dist_data.get("distances", [[]])

    if durations and durations[0] and len(durations[0]) > 1:
        time_min = round(durations[0][1] / 60, 1)
        dist_km = round(distances[0][1] / 1000, 1) if distances and distances[0] and len(distances[0]) > 1 else "N/A"
        return f"Distance from '{prop.get('property_name', property_name)}' to '{landmark_name}': {dist_km} km ({time_min} min by car)"

    return "Could not calculate distance."


# ---------------------------------------------------------------------------
# Tool: estimate_commute (NEW — driving + transit estimate)
# ---------------------------------------------------------------------------
async def estimate_commute(
    user_id: str, property_name: str, destination: str, city: str = "", **kwargs
) -> str:
    """Estimate commute from a property to a destination via car AND public transit."""
    prop = _find_prop(user_id, property_name)
    if not prop:
        return f"Property '{property_name}' not found."

    prop_lat = float(prop.get("property_lat", 0))
    prop_long = float(prop.get("property_long", 0))
    if not prop_lat or not prop_long:
        return "Property coordinates not available."

    # Resolve city from property data or param
    resolved_city = city or prop.get("city", prop.get("property_city", "")).strip()

    # --- Driving estimate via OSRM ---
    driving_info = ""
    dest_lat, dest_long = 0.0, 0.0
    try:
        geo_data = await http_post(
            f"{settings.RENTOK_API_BASE_URL}/property/getLatLongProperty",
            json={"address": destination},
        )
        dest_lat = float(geo_data.get("lat", geo_data.get("latitude", 0)))
        dest_long = float(geo_data.get("long", geo_data.get("longitude", 0)))
    except Exception as e:
        logger.warning("Geocoding destination failed: %s", e)

    if dest_lat and dest_long:
        try:
            dist_data = await http_get(
                f"http://maps.rentok.com/table/v1/driving/{prop_long},{prop_lat};{dest_long},{dest_lat}",
                params={"sources": "0", "api_key": settings.OSRM_API_KEY},
            )
            durations = dist_data.get("durations", [[]])
            distances = dist_data.get("distances", [[]])
            if durations and durations[0] and len(durations[0]) > 1:
                drive_min = round(durations[0][1] / 60, 0)
                drive_km = round(distances[0][1] / 1000, 1) if distances and distances[0] and len(distances[0]) > 1 else None
                driving_info = f"By car: ~{int(drive_min)} min"
                if drive_km:
                    driving_info += f" ({drive_km} km)"
        except Exception as e:
            logger.warning("OSRM driving estimate failed: %s", e)

    # --- Transit estimate ---
    transit_info = ""

    # Find nearest station to property
    prop_stations = await _find_nearest_station(prop_lat, prop_long, radius=2000)

    # Find nearest station to destination
    dest_stations = []
    if dest_lat and dest_long:
        dest_stations = await _find_nearest_station(dest_lat, dest_long, radius=2000)

    if prop_stations and dest_stations and resolved_city:
        # Try to find a shared transit line
        best_route = None
        best_total = float("inf")
        for ps in prop_stations[:3]:
            for ds in dest_stations[:3]:
                route = _estimate_transit_time(ps["name"], ds["name"], resolved_city)
                if route:
                    total = ps["walk_min"] + route["travel_min"] + ds["walk_min"]
                    if total < best_total:
                        best_total = total
                        best_route = {
                            "origin_station": ps["name"],
                            "dest_station": ds["name"],
                            "walk_to": int(ps["walk_min"]),
                            "walk_from": int(ds["walk_min"]),
                            "line": route["line"],
                            "stations": route["stations"],
                            "ride_min": int(route["travel_min"]),
                            "total_min": int(total),
                            "mode": route["mode"],
                        }

        if best_route:
            mode_label = "metro" if best_route["mode"] == "metro" else "train"
            transit_info = (
                f"By {mode_label}: ~{best_route['total_min']} min "
                f"(walk {best_route['walk_to']} min → {best_route['origin_station']} → "
                f"{best_route['line']} ({best_route['stations']} stops) → "
                f"{best_route['dest_station']} → walk {best_route['walk_from']} min)"
            )

    # If no shared line found but property is near a station, still mention it
    if not transit_info and prop_stations:
        nearest = prop_stations[0]
        transit_info = (
            f"Nearest station: {nearest['name']} ({nearest['distance_km']} km, "
            f"~{int(nearest['walk_min'])} min walk)"
        )

    # Build response
    prop_name = prop.get("property_name", property_name)
    parts = [f"Commute from '{prop_name}' to '{destination}':"]
    if driving_info:
        parts.append(f"🚗 {driving_info}")
    if transit_info:
        parts.append(f"🚇 {transit_info}")
    if not driving_info and not transit_info:
        parts.append("Could not estimate commute. Try fetch_landmarks for a straight-line distance.")

    return "\n".join(parts)
