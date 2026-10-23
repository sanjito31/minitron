"""Loader contract adapter for Clock's original analog/digital renderer.

No App is constructed or registered here. Clock has no upstream data dependency;
the services argument is accepted for the common module interface.
"""

from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

try:
    from utils.draw import draw_time
except ModuleNotFoundError as exc:
    if exc.name not in ("utils", "utils.draw"):
        raise
    from apps.api.utils.draw import draw_time


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


def update(config: dict, *, services: object = None) -> tuple[dict, datetime]:
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
    expires_at = min(next_minute, now + timedelta(seconds=min(ttl, 60)))
    return {
        "time_str": f"{hour_text}:{current_time.minute:02d}{meridian}",
        "expires_at": expires_at,
    }, expires_at


def render(data: dict, config: dict) -> tuple[bytes, datetime]:
    """Keep the updater's absolute deadline rather than renewing it at render."""
    graphic = draw_time(
        data["time_str"],
        width=config.get("width", DEFAULT_CONFIG["width"]),
        height=config.get("height", DEFAULT_CONFIG["height"]),
        fontsize=config.get("fontsize", DEFAULT_CONFIG["fontsize"]),
        bg=tuple(config.get("bg", DEFAULT_CONFIG["bg"])),
        fg=tuple(config.get("fg", DEFAULT_CONFIG["fg"])),
    )
    return graphic, data["expires_at"]
