"""Nearest airborne aircraft, with optional ADSBDB route information."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont
import requests


NAME = "Flights Overhead"
AUTHOR = ""
DEFAULT_CONFIG = {
    "lat": None,
    "lon": None,
    "latmin": None,
    "latmax": None,
    "lomin": None,
    "lomax": None,
    "ttl": 120,
    "timeout": 10,
    "max_route_lookups": 3,
    "width": 64,
    "height": 32,
    "fontsize": 8,
    "bg": [0, 0, 0],
    "fg": [255, 255, 255],
}
API_ROOT = Path(__file__).resolve().parents[1]
STATES_URL = "https://opensky-network.org/api/states/all"
ROUTE_URL = "https://api.adsbdb.com/v0/callsign/"


def update(config: dict, *, services: object = None) -> tuple[dict, datetime] | None:
    environment = dotenv_values(API_ROOT / ".env") | dict(os.environ)

    def setting(key):
        value = config.get(key)
        return value if value is not None else environment.get(key.upper())

    lat, lon = setting("lat"), setting("lon")
    if lat is None or lon is None:
        return None
    latitude, longitude = float(lat), float(lon)
    params = {
        parameter: setting(key) if setting(key) is not None else fallback
        for key, parameter, fallback in (
            ("latmin", "lamin", latitude - 0.2), ("latmax", "lamax", latitude + 0.2),
            ("lomin", "lomin", longitude - 0.2), ("lomax", "lomax", longitude + 0.2),
        )
    }
    ttl = config.get("ttl", DEFAULT_CONFIG["ttl"])
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl <= 0:
        raise ValueError("Flights ttl must be a positive finite number of seconds.")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl)
    timeout = config.get("timeout", DEFAULT_CONFIG["timeout"])
    client = getattr(services, "http", requests)
    token = environment.get("OPENSKY_ACCESS_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = client.get(STATES_URL, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if payload.get("time"):
            expires = min(expires, datetime.fromtimestamp(payload["time"], timezone.utc) + timedelta(seconds=ttl))
        candidates = []
        for state in payload.get("states") or []:
            if not isinstance(state, list) or len(state) < 14 or state[8]:
                continue
            callsign = state[1].strip() if isinstance(state[1], str) else ""
            if not callsign or state[5] is None or state[6] is None:
                continue
            altitude = state[13] if state[13] is not None else state[7] or 0
            distance, heading = _distance_and_bearing(
                latitude, longitude, float(state[6]), float(state[5]), float(altitude)
            )
            candidates.append((distance, heading, callsign))
        candidates.sort()
    except (requests.RequestException, ValueError, KeyError, TypeError, OverflowError):
        return None

    data = {
        "flight_no": "No flights", "airline": "", "distance": None, "bearing": None,
        "origin": {"code": "---"}, "destination": {"code": "---"},
        "expires_at": expires,
    }
    if not candidates:
        return data, expires
    nearest = candidates[0]
    data.update(distance=nearest[0], bearing=nearest[1], flight_no=nearest[2])
    maximum = max(0, int(config.get("max_route_lookups", DEFAULT_CONFIG["max_route_lookups"])))
    for distance, heading, callsign in candidates[:maximum]:
        try:
            response = client.get(ROUTE_URL + quote(callsign, safe=""), timeout=timeout)
            response.raise_for_status()
            route = response.json()["response"]["flightroute"]
            if not isinstance(route, dict):
                continue
            airline = route.get("airline")
            data.update(
                flight_no=route.get("callsign") or callsign,
                airline=airline.get("name", "") if isinstance(airline, dict) else "",
                distance=distance, bearing=heading,
            )
            for key in ("origin", "destination"):
                airport = route.get(key) or {}
                if not isinstance(airport, dict):
                    airport = {}
                data[key] = {
                    "code": airport.get("iata_code") or airport.get("icao_code") or "---",
                    "name": airport.get("name", ""),
                    "city": airport.get("municipality", ""),
                    "country": airport.get("country_name", ""),
                }
            break
        except (requests.RequestException, ValueError, KeyError, TypeError):
            continue
    return data, expires


def _distance_and_bearing(lat1, lon1, lat2, lon2, altitude):
    """Use latitude/longitude consistently; OpenSky vectors store longitude first."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    surface_distance = 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, haversine))))
    bearing = math.degrees(math.atan2(
        math.sin(delta_lon) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon),
    )) % 360
    return math.hypot(surface_distance, altitude), bearing


def render(data: dict, config: dict) -> tuple[bytes, datetime]:
    width = config.get("width", DEFAULT_CONFIG["width"])
    height = config.get("height", DEFAULT_CONFIG["height"])
    image = Image.new("RGB", (width, height), tuple(config.get("bg", DEFAULT_CONFIG["bg"])))
    draw = ImageDraw.Draw(image)
    foreground = tuple(config.get("fg", DEFAULT_CONFIG["fg"]))
    fontsize = config.get("fontsize", DEFAULT_CONFIG["fontsize"])
    try:
        font = ImageFont.truetype(str(API_ROOT / "fonts/Minecraft.ttf"), fontsize)
    except OSError:
        font = ImageFont.load_default(fontsize)

    logo_name = "generic_plane.png"
    for keyword, filename in (
        ("american", "aa.jpg"), ("delta", "delta.jpg"), ("united", "united.png"),
        ("southwest", "southwest.jpg"), ("spirit", "spirit.jpg"),
    ):
        if keyword in data["airline"].lower():
            logo_name = filename
            break
    try:
        with Image.open(API_ROOT / "assets/airline_logos" / logo_name) as logo:
            image.paste(logo.convert("RGB").resize((16, 16)), (2, 2))
    except OSError:
        pass

    route = f"{data['origin']['code']}>{data['destination']['code']}"
    for value, x, y, right_align in (
        (route, width - 2, 2, True),
        (data["flight_no"], width - 2, 12, True),
        (data["airline"], 2, height - fontsize - 2, False),
    ):
        box = draw.textbbox((0, 0), value, font=font)
        if right_align:
            x -= box[2] - box[0]
        draw.text((x - box[0], y - box[1]), value, font=font, fill=foreground)
    output = BytesIO()
    image.save(output, "WEBP")
    return output.getvalue(), data["expires_at"]
