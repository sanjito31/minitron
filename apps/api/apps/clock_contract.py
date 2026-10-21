"""Contract-compliant copy of Clock's analog/digital graphic.

No App is constructed or registered here. Clock has no upstream data dependency;
the services argument is accepted for the common module interface.
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from math import cos, isfinite, radians, sin
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont


NAME = "Clock"
AUTHOR = ""  # Set the publisher's handle when distributing the app.
DEFAULT_CONFIG = {
    "timezone": "America/New_York",
    "24hourtime": False,
    "ttl": 60,
    "width": 64,
    "height": 32,
    "fontsize": 15,
    "bg": [0, 0, 0],
    "fg": [255, 255, 255],
}


def update(config: dict, *, services: object = None) -> dict:
    now = datetime.now(timezone.utc)
    current_time = now.astimezone(
        ZoneInfo(config.get("timezone", DEFAULT_CONFIG["timezone"]))
    )
    use_24_hour_time = config.get("24hourtime", DEFAULT_CONFIG["24hourtime"])
    if not isinstance(use_24_hour_time, bool):
        raise ValueError("Clock 24hourtime must be a boolean.")
    hour = current_time.hour if use_24_hour_time else current_time.hour % 12 or 12
    hour_text = f"{hour:02d}" if use_24_hour_time else str(hour)
    meridian = "" if use_24_hour_time else ("AM" if current_time.hour < 12 else "PM")
    ttl = config.get("ttl", DEFAULT_CONFIG["ttl"])
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
        raise ValueError("Clock ttl must be a positive finite number of seconds.")
    if ttl <= 0 or (isinstance(ttl, float) and not isfinite(ttl)):
        raise ValueError("Clock ttl must be a positive finite number of seconds.")
    next_minute = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return {
        "time_str": f"{hour_text}:{current_time.minute:02d}{meridian}",
        "expires_at": min(next_minute, now + timedelta(seconds=min(ttl, 60))),
    }


def render(data: dict, config: dict) -> tuple[bytes, datetime]:
    """Keep the updater's absolute deadline rather than renewing it at render."""
    return _draw_time(data["time_str"], config), data["expires_at"]


def _load_font(name: str, size: int):
    path = Path(__file__).resolve().parents[1] / "fonts" / "JetBrainsMono" / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size)


def _text_size(draw, text, font):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _draw_text(draw, text, x, y, font, color):
    left, top, _, _ = draw.textbbox((0, 0), text, font=font)
    draw.text((x - left, y - top), text, font=font, fill=color)


def _draw_time(text: str, config: dict) -> bytes:
    width = config.get("width", DEFAULT_CONFIG["width"])
    height = config.get("height", DEFAULT_CONFIG["height"])
    fontsize = config.get("fontsize", DEFAULT_CONFIG["fontsize"])
    foreground = tuple(config.get("fg", DEFAULT_CONFIG["fg"]))
    background = tuple(config.get("bg", DEFAULT_CONFIG["bg"]))
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    font = _load_font("JetBrainsMonoNL-Bold.ttf", fontsize)

    hour_text, rest = text.split(":")
    minute_text, meridian = rest[:2], rest[2:]
    hour_width, hour_height = _text_size(draw, hour_text, font)
    minute_width, minute_height = _text_size(draw, minute_text, font)
    vertical_space = (height - hour_height - minute_height) // 3
    horizontal_space = (width // 2 - max(hour_width, minute_width)) // 2
    _draw_text(
        draw, hour_text, width - horizontal_space - hour_width,
        vertical_space, font, foreground,
    )
    _draw_text(
        draw, minute_text, width - horizontal_space - minute_width,
        height - vertical_space - minute_height, font, foreground,
    )

    x, y = width // 4, height // 2
    radius = x - vertical_space
    draw.circle((x, y), radius, outline=foreground, width=1)
    minute_angle = radians(360 * int(minute_text) / 60)
    hour_angle = radians(360 * ((int(hour_text) % 12) * 60 + int(minute_text)) / 720)
    for angle, length in ((minute_angle, 0.9), (hour_angle, 0.5)):
        hand = (
            x + radius * length * sin(angle),
            y - radius * length * cos(angle),
        )
        draw.line([(x, y), hand], fill=foreground, width=1)

    if meridian == "PM":
        small_font = _load_font("JetBrainsMonoNL-Thin.ttf", 4)
        _draw_text(
            draw, "P", width - horizontal_space,
            height - vertical_space - minute_height, small_font, foreground,
        )

    blinking_frame = image.copy()
    _draw_text(
        ImageDraw.Draw(blinking_frame), ":", width - horizontal_space - 2,
        vertical_space + 2, font, foreground,
    )
    buffer = BytesIO()
    image.save(
        buffer, "WEBP", save_all=True, append_images=[blinking_frame],
        duration=1000, loop=0,
    )
    return buffer.getvalue()
