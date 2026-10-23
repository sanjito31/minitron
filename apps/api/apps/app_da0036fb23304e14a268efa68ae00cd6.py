"""Current weather graphic; importing the module does not contact the provider."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from math import isfinite
import os
from pathlib import Path

from dotenv import dotenv_values
from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests


NAME = "Weather"
AUTHOR = ""
DEFAULT_CONFIG = {
    "lat": None,
    "lon": None,
    "units": "imperial",
    "ttl": 600,
    "timeout": 10,
    "width": 64,
    "height": 32,
    "fontsize": 8,
    "bg": [0, 0, 0],
    "fg": [255, 255, 255],
}
API_ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://api.openweathermap.org/data/2.5/weather"


def update(config: dict, *, services: object = None) -> tuple[dict, datetime] | None:
    environment = dotenv_values(API_ROOT / ".env") | dict(os.environ)
    api_key = environment.get("OPEN_WEATHER_API_KEY")
    lat = config.get("lat")
    lon = config.get("lon")
    lat = lat if lat is not None else environment.get("LAT")
    lon = lon if lon is not None else environment.get("LON")
    if not api_key or lat is None or lon is None:
        return None
    units = config.get("units", DEFAULT_CONFIG["units"])
    if units not in ("imperial", "metric", "standard"):
        raise ValueError("Weather units must be imperial, metric, or standard.")
    ttl = config.get("ttl", DEFAULT_CONFIG["ttl"])
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not isfinite(ttl) or ttl <= 0:
        raise ValueError("Weather ttl must be a positive finite number of seconds.")
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    client = getattr(services, "http", requests)
    try:
        response = client.get(
            API_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": units},
            timeout=config.get("timeout", DEFAULT_CONFIG["timeout"]),
        )
        response.raise_for_status()
        weather = response.json()
        temperatures = weather["main"]
        data: dict = {
            field: str(round(temperatures[field]))
            for field in ("temp", "feels_like", "temp_max", "temp_min")
        }
        data.update(
            description=str(weather["weather"][0]["main"]),
            unit={"imperial": "F", "metric": "C", "standard": "K"}[units],
            expires_at=expires,
        )
        return data, expires
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None


def render(data: dict, config: dict) -> tuple[bytes, datetime]:
    width = config.get("width", DEFAULT_CONFIG["width"])
    height = config.get("height", DEFAULT_CONFIG["height"])
    background = tuple(config.get("bg", DEFAULT_CONFIG["bg"]))
    foreground = tuple(config.get("fg", DEFAULT_CONFIG["fg"]))
    fontsize = config.get("fontsize", DEFAULT_CONFIG["fontsize"])
    try:
        font = ImageFont.truetype(str(API_ROOT / "fonts/early_gameboy.ttf"), fontsize)
    except OSError:
        font = ImageFont.load_default(fontsize)

    description = data["description"]
    icon_name = "cloudy.png"
    for keyword, name in (
        ("clear", "sunny-day.png"), ("cloud", "cloudy.png"),
        ("rain", "rainy.png"), ("drizzle", "rainy.png"), ("thunder", "rainy.png"),
    ):
        if keyword in description.lower():
            icon_name = name
            break
    try:
        with Image.open(API_ROOT / "assets/weather" / icon_name) as image:
            icon = ImageOps.invert(image.convert("RGBA").convert("RGB")).resize((24, 24))
    except OSError:
        icon = None

    # Preserve the original reveal animation with call-local image buffers.
    temperature = data["temp"] + data["unit"]
    measure = ImageDraw.Draw(Image.new("RGB", (width, height)))
    desc_box = measure.textbbox((0, 0), description, font=font)
    temp_box = measure.textbbox((0, 0), temperature, font=font)
    desc_height = desc_box[3] - desc_box[1]
    temp_height = temp_box[3] - temp_box[1]
    layers = []
    if icon is not None:
        layers.append((icon, 0, 0))
    for text, box, y in (
        (description, desc_box, height - 3 - desc_height),
        (temperature, temp_box, height - 5 - desc_height - temp_height),
    ):
        text_width, text_height = int(box[2] - box[0]), int(box[3] - box[1])
        layer = Image.new("RGB", (max(1, text_width), max(1, text_height)), background)
        ImageDraw.Draw(layer).text((-box[0], -box[1]), text, font=font, fill=foreground)
        layers.append((layer, width - 3 - text_width, y))

    frames = []
    for frame in range(10):
        image = Image.new("RGB", (width, height), background)
        for layer, x, y in layers:
            visible = round(layer.height * frame / 9)
            if visible:
                crop_y = layer.height - visible
                image.paste(layer.crop((0, crop_y, layer.width, layer.height)), (x, y + crop_y))
        frames.append(image)
    output = BytesIO()
    frames[0].save(
        output, "WEBP", save_all=True, append_images=frames[1:],
        duration=[100] * 9 + [10000], loop=0,
    )
    return output.getvalue(), data["expires_at"]
