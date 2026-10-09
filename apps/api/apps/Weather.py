from models.App import App
from utils.TimeKeeper import now
from utils.draw import Text, DISP_HEIGHT, DISP_WIDTH
from config import settings
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from io import BytesIO

ICON_DIR = "./assets/weather"
ICON_SIZE = 16
WEATHER_ICONS = {
    "clear": f"{ICON_DIR}/sunny-day.png",
    "clouds": f"{ICON_DIR}/cloudy.png",
    "rain": f"{ICON_DIR}/rainy.png",
    "drizzle": f"{ICON_DIR}/rainy.png",
    "thunderstorm": f"{ICON_DIR}/rainy.png",
}
DEFAULT_ICON = f"{ICON_DIR}/cloudy.png"

WEATHER_API_REQ_INTERVAL = 600  # 10 minutes

def weather_update(config: dict) -> dict | None:
    url = config.get("api_url")

    if isinstance(url, str):
        resp = requests.get(url)

        weather = resp.json()

        if resp.status_code == 200:
            cache = {
                "temp": str(round(weather["main"]["temp"])),
                "feels_like": str(round(weather["main"]["feels_like"])),
                "temp_max": str(round(weather["main"]["temp_max"])),
                "temp_min": str(round(weather["main"]["temp_min"])),
                "description": str(weather["weather"][0]["main"])
            }
            return cache
    return None
    



def weather_render(cache: dict) -> bytes:

    return draw_weather(weather=cache)
    

def draw_weather(   weather: dict,
                    width: int = DISP_WIDTH,
                    height: int = DISP_HEIGHT,
                    fontsize: int = 8,
                    bg: tuple = (0, 0, 0),
                    fg: tuple = (255, 255, 255),
                ):

    tmp = Image.new("RGB", (width, height))
    tmp_draw = ImageDraw.Draw(tmp)

    try:
        font = ImageFont.truetype("./fonts/early_gameboy.ttf", fontsize, layout_engine=ImageFont.Layout.BASIC)
    except Exception as e:
        font = ImageFont.load_default()

    temp = Text(weather["temp"]+"F", tmp_draw, font)
    description = Text(weather["description"], tmp_draw, font)

    margin = 2

    # -- Load weather icon --
    desc_lower = weather.get("description", "").lower()
    icon_path = DEFAULT_ICON
    for keyword, path in WEATHER_ICONS.items():
        if keyword in desc_lower:
            icon_path = path
            break
    try:
        icon_img = Image.open(icon_path).convert("RGBA").convert("RGB")
        icon_img = ImageOps.invert(icon_img)
        icon_img = icon_img.resize((24, 24))
    except Exception:
        icon_img = None

    # -- Final positions for each element --
    icon_x, icon_y = 0, 0
    icon_w, icon_h = 24, 24

    desc_x = width - 1 - margin - description.width
    desc_y = height - 1 - margin - description.height

    temp_x = width - 1 - margin - temp.width
    temp_y = height - 1 - (2 * margin) - temp.height - description.height

    # -- Define elements: (name, final_y, height, stagger_frame) --
    # Each element starts hidden below its final box and slides up
    ANIM_FRAMES = 10      # frames per element to fully reveal
    FRAME_DURATION = 100  # ms per frame

    elements = [
        {"name": "icon",  "start_delay": 0},
        {"name": "temp",  "start_delay": 0},
        {"name": "desc",  "start_delay": 0},
    ]

    total_frames = ANIM_FRAMES

    frames = []
    for f in range(total_frames):
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        for el in elements:
            progress = max(0, min(1.0, (f - el["start_delay"]) / (ANIM_FRAMES - 1)))

            if el["name"] == "icon" and icon_img is not None:
                # Reveal icon: clip from bottom up
                visible_h = int(icon_h * progress)
                if visible_h > 0:
                    crop_y = icon_h - visible_h
                    cropped = icon_img.crop((0, crop_y, icon_w, icon_h))
                    img.paste(cropped, (icon_x, icon_y + crop_y))

            elif el["name"] == "temp":
                visible_h = int(temp.height * progress)
                if visible_h > 0:
                    # Render temp onto a small buffer, crop from bottom
                    tbuf = Image.new("RGB", (temp.width + 2, temp.height + 2))
                    tdraw = ImageDraw.Draw(tbuf)
                    t = Text(weather["temp"]+"F", tdraw, font)
                    tdraw.text(t.coords(0, 0), t.text, font=font, fill=fg)
                    crop_y = temp.height - visible_h
                    cropped = tbuf.crop((0, crop_y, temp.width + 2, temp.height))
                    paste_y = temp_y + crop_y
                    img.paste(cropped, (temp_x, paste_y))

            elif el["name"] == "desc":
                visible_h = int(description.height * progress)
                if visible_h > 0:
                    dbuf = Image.new("RGB", (description.width + 2, description.height + 2))
                    ddraw = ImageDraw.Draw(dbuf)
                    d = Text(weather["description"], ddraw, font)
                    ddraw.text(d.coords(0, 0), d.text, font=font, fill=fg)
                    crop_y = description.height - visible_h
                    cropped = dbuf.crop((0, crop_y, description.width + 2, description.height))
                    paste_y = desc_y + crop_y
                    img.paste(cropped, (desc_x, paste_y))

        frames.append(img)

    durations = [FRAME_DURATION] * (len(frames) - 1) + [10000]

    buf = BytesIO()
    frames[0].save(
        buf, "WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0
    )
    return buf.getvalue()
    

weather_app = App(
        id="weather",
        name="Weather",
        ttl=WEATHER_API_REQ_INTERVAL,
        enabled=True,
        update_fn=weather_update,
        render_fn=weather_render,
        config={
            "api_url": f"https://api.openweathermap.org/data/2.5/weather?lat={settings.LAT}&lon={settings.LON}&appid={settings.OPEN_WEATHER_API_KEY}&units=imperial"
        }
    )