from datetime import datetime
from pytz import timezone as pytz_timezone

from models.App import App
from utils.draw import DISP_HEIGHT, DISP_WIDTH, Text

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from math import sin, cos, radians

DEFAULT_TIMEZONE = "US/Eastern"
DEFAULT_FORMAT = "%-I:%M%p"


def clock_update(config: dict) -> dict | None:
    tz = config.get("timezone", DEFAULT_TIMEZONE)
    fmt = config.get("format_str", DEFAULT_FORMAT)

    current_time = datetime.now(pytz_timezone(tz))
    ttl = 60 - current_time.second

    cache = {
        "time_str": current_time.strftime(fmt),
        "ttl": ttl,
    }
    return cache


def clock_render(cache: dict) -> bytes:
    return draw_time(cache["time_str"])


def draw_time(text: str,
        width: int = DISP_WIDTH,
        height: int = DISP_HEIGHT,
        fontsize: int = 15,
        bg: tuple = (0, 0, 0),
        fg: tuple = (255, 255, 255),
        align: tuple = ('c', 'c')
        ):
    
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    frames = []

    try:
        font = ImageFont.truetype("./fonts/JetBrainsMono/JetBrainsMonoNL-Bold.ttf", fontsize)
    except OSError:
        font = ImageFont.load_default(fontsize)


    hour_text, rest = text.split(":")
    minute_text = rest[:2]
    meridian_text = rest[2:]

    hour = Text(hour_text, draw, font)
    minute = Text(minute_text, draw, font)


    v_space = (height - hour.height - minute.height) // 3
    h_space = (((width // 2) - max(hour.width, minute.width)) // 2)


    draw.text(hour.coords(width - h_space - hour.width, v_space), hour.text, font=hour.font, fill=fg)
    draw.text(minute.coords(width - h_space - minute.width, height - v_space - minute.height), minute.text, font=minute.font, fill=fg)

    # circle center
    x = width // 4
    y = height // 2
    radius = x - v_space

    draw.circle((x,y), radius, fill=None, outline=fg, width=1)


    # Minute hand
    MINUTES_PER_HOUR = 60.0
    MINUTE_HAND_LENGTH = 0.9  # Fraction of Radius
    hour_frac = (float(minute.text) / MINUTES_PER_HOUR)
    min_hand_angle = 360 * hour_frac

    x_min_hand = (radius * MINUTE_HAND_LENGTH) * sin(radians(min_hand_angle)) + x
    y_min_hand = (radius * MINUTE_HAND_LENGTH) * -cos(radians(min_hand_angle)) + y

    draw.line([(x, y), (x_min_hand, y_min_hand)], fill=fg, width=1)


    # Hour hand
    HOURS_PER_CIRCLE = 12
    MINUTES_PER_CIRCLE = HOURS_PER_CIRCLE * MINUTES_PER_HOUR
    HOUR_HAND_LENGTH = 0.5 # Fraction of Radius


    minutes_past_twelve = ((int(hour.text) % HOURS_PER_CIRCLE) * MINUTES_PER_HOUR + int(minute.text)) 
    hour_hand_angle = 360 * (minutes_past_twelve / MINUTES_PER_CIRCLE)

    x_hour_hand = (radius * HOUR_HAND_LENGTH) * sin(radians(hour_hand_angle)) + x
    y_hour_hand = (radius * HOUR_HAND_LENGTH) * -cos(radians(hour_hand_angle)) + y

    draw.line([(x,y), (x_hour_hand, y_hour_hand)], fill=fg, width=1)

    # Meridian
    if meridian_text == "PM":
        p = Text("P", draw, font=ImageFont.truetype("./fonts/JetBrainsMono/JetBrainsMonoNL-Thin.ttf", 4))
        draw.text(p.coords(width - h_space, height - v_space - minute.height), p.text, fill=fg)

    frames.append(img)
    
    f2 = img.copy()
    f2draw = ImageDraw.Draw(f2)
    colon = Text(":", font=font, draw=f2draw)
    f2draw.text(colon.coords(width-h_space-2, v_space+2), colon.text, font=colon.font, fill=fg)

    frames.append(f2)

    


    buf = BytesIO()
    # img.save(buf, "WEBP")

    frames[0].save(
        buf, "WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=1000,
        loop=0
    )
    return buf.getvalue()


clock_app = App(
        id="clock",
        name="Clock",
        update_fn=clock_update,
        render_fn=clock_render,
        config={}
    )
