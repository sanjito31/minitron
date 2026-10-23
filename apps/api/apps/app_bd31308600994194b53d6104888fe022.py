"""Configurable MTA subway arrivals using the GTFS-realtime feed."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from math import isfinite
from pathlib import Path

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2
from PIL import Image, ImageDraw, ImageFont
import requests


NAME = "MTA"
AUTHOR = ""
DEFAULT_CONFIG = {
    "api_url": "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm",
    "stations": {"D22": "GRAND", "F15": "DELANCEY", "M18": "ESSEX"},
    "lines": ["B", "D", "F", "M"],
    "sections": [{"label": "D", "lines": ["B", "D"]}, {"label": "F", "lines": ["F"]}],
    "min_wait": 4,
    "max_wait": 30,
    "ttl": 30,
    "timeout": 10,
    "width": 64,
    "height": 32,
    "fontsize": 8,
    "bg": [0, 0, 0],
    "fg": [255, 255, 255],
}
API_ROOT = Path(__file__).resolve().parents[1]


def update(config: dict, *, services: object = None) -> tuple[dict, datetime] | None:
    ttl = config.get("ttl", DEFAULT_CONFIG["ttl"])
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not isfinite(ttl) or ttl <= 0:
        raise ValueError("MTA ttl must be a positive finite number of seconds.")
    now = datetime.now(timezone.utc)
    client = getattr(services, "http", requests)
    try:
        response = client.get(
            config.get("api_url", DEFAULT_CONFIG["api_url"]),
            timeout=config.get("timeout", DEFAULT_CONFIG["timeout"]),
        )
        response.raise_for_status()
        feed = getattr(gtfs_realtime_pb2, "FeedMessage")()
        feed.ParseFromString(response.content)
    except (requests.RequestException, DecodeError):
        return None

    stations = config.get("stations", DEFAULT_CONFIG["stations"])
    routes = {
        line: {"station": "", "uptown_arrivals": [], "downtown_arrivals": []}
        for line in config.get("lines", DEFAULT_CONFIG["lines"])
    }
    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip = entity.trip_update
        line = trip.trip.route_id
        if line not in routes:
            continue
        for stop in trip.stop_time_update:
            station, direction = stop.stop_id[:-1], stop.stop_id[-1:]
            if station not in stations or direction not in ("N", "S"):
                continue
            if stop.HasField("arrival") and stop.arrival.HasField("time"):
                arrival = stop.arrival.time
            elif stop.HasField("departure") and stop.departure.HasField("time"):
                arrival = stop.departure.time
            else:
                continue
            if arrival <= now.timestamp():
                continue
            route = routes[line]
            route["station"] = stations[station]
            key = "uptown_arrivals" if direction == "N" else "downtown_arrivals"
            route[key].append(arrival)
    for route in routes.values():
        route["uptown_arrivals"].sort()
        route["downtown_arrivals"].sort()

    expires = now + timedelta(seconds=ttl)
    if feed.header.timestamp:
        expires = min(expires, datetime.fromtimestamp(feed.header.timestamp, timezone.utc) + timedelta(seconds=ttl))
    return {"routes": routes, "expires_at": expires}, expires


def render(data: dict, config: dict) -> tuple[bytes, datetime]:
    width = config.get("width", DEFAULT_CONFIG["width"])
    height = config.get("height", DEFAULT_CONFIG["height"])
    image = Image.new("RGB", (width, height), tuple(config.get("bg", DEFAULT_CONFIG["bg"])))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(
            str(API_ROOT / "fonts/Lexis-Regular.ttf"), config.get("fontsize", DEFAULT_CONFIG["fontsize"])
        )
    except OSError:
        font = ImageFont.load_default(config.get("fontsize", DEFAULT_CONFIG["fontsize"]))
    sections = config.get("sections", DEFAULT_CONFIG["sections"])
    now = datetime.now(timezone.utc)
    expires = data["expires_at"]
    section_height = height // max(1, len(sections))
    foreground = tuple(config.get("fg", DEFAULT_CONFIG["fg"]))
    minimum = config.get("min_wait", DEFAULT_CONFIG["min_wait"])
    maximum = config.get("max_wait", DEFAULT_CONFIG["max_wait"])

    def text(value, x, y, color):
        box = draw.textbbox((0, 0), value, font=font)
        draw.text((x - box[0], y - box[1]), value, font=font, fill=color)

    for index, section in enumerate(sections):
        top = index * section_height
        center_y = top + section_height // 2
        draw.ellipse((1, center_y - 5, 11, center_y + 5), fill=(255, 153, 0))
        text(section["label"], 4, center_y - 3, (0, 0, 0))
        for direction, offset, color in (
            ("uptown_arrivals", 0, (255, 204, 0)),
            ("downtown_arrivals", section_height // 2, foreground),
        ):
            arrivals = sorted(
                arrival for line in section["lines"]
                for arrival in data["routes"].get(line, {}).get(direction, [])
            )
            waits = []
            for arrival in arrivals:
                seconds = arrival - now.timestamp()
                if seconds <= 0:
                    continue
                wait = int(seconds // 60)
                if wait <= maximum:
                    # Refresh when this countdown next changes, even if data lives longer.
                    next_change = datetime.fromtimestamp(arrival - wait * 60, timezone.utc)
                    if next_change <= now:
                        next_change = now + timedelta(milliseconds=1)
                    expires = min(expires, next_change)
                if minimum <= wait <= maximum:
                    waits.append(str(wait))
            text(
                ",".join(waits[:3]) or "-", 14, top + offset + 1, color,
            )
        if index:
            for x in range(0, width, 2):
                draw.point((x, top), fill=(120, 120, 120))
    output = BytesIO()
    image.save(output, "WEBP")
    return output.getvalue(), expires
