import requests
from google.transit import gtfs_realtime_pb2
import time
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

from models.App import App
from utils.draw import Text

ROUTES_CSV_PATH = "./assets/gtfs_subway/stops.txt"
BDFM_API_URL = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-bdfm"

MY_STATIONS = {
    "D22": "GRAND",
    "F15": "DELANCEY",
    "M18": "ESSEX"
}

MY_LINES = ["B", "D", "F", "M"]

MTA_TTL = 30  # seconds


def getMTA_realtime():

    now = int(time.time())

    feed = gtfs_realtime_pb2.FeedMessage()  # type: ignore[attr-defined]
    resp = requests.get(BDFM_API_URL)
    feed.ParseFromString(resp.content)

    rt_updates = {
        line: {
            "station": "",
            "uptown_waits": [],
            "downtown_waits": []
        }
        for line in MY_LINES
    }

    for entity in feed.entity:
        if entity.HasField('trip_update'):
            tu = entity.trip_update
            line = tu.trip.route_id
            for stop in tu.stop_time_update:
                parent_stop = stop.stop_id[:-1]
                direction = stop.stop_id[-1]
                if parent_stop in tuple(MY_STATIONS.keys()):
                    wait = max(0, ((stop.arrival.time - now) // 60))
                    if wait > 30:
                        continue
                    rt_updates[f"{line}"]["station"] = MY_STATIONS[parent_stop]
                    if direction == "N":
                        rt_updates[f"{line}"]["uptown_waits"].append(wait)
                    else:
                        rt_updates[f"{line}"]["downtown_waits"].append(wait)

    for line in rt_updates.values():
        line["uptown_waits"].sort()
        line["downtown_waits"].sort()

    return rt_updates


# -- AppNew functions --

def mta_update(config: dict) -> dict | None:
    cache = getMTA_realtime()
    return cache


def mta_render(cache: dict) -> bytes:
    if cache is None:
        cache = {line: {"uptown_waits": [], "downtown_waits": []} for line in MY_LINES}

    DISP_WIDTH = 64
    DISP_HEIGHT = 32
    SECTION_HEIGHT = 16  # two sections: D on top, F on bottom
    BDFM_ORANGE = (255, 153, 0)
    WHITE = (255, 255, 255)
    YELLOW = (255, 204, 0)
    DIM = (120, 120, 120)
    MIN_WAIT = 4

    img = Image.new("RGB", (DISP_WIDTH, DISP_HEIGHT))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("./fonts/Lexis-Regular.ttf", 8)
    except OSError:
        font = ImageFont.load_default(7)

    # -- Combine B + D waits, merge and sort --
    b_data = cache.get("B", {"uptown_waits": [], "downtown_waits": []})
    d_data = cache.get("D", {"uptown_waits": [], "downtown_waits": []})
    bd_up = sorted(b_data["uptown_waits"] + d_data["uptown_waits"])
    bd_dn = sorted(b_data["downtown_waits"] + d_data["downtown_waits"])

    f_data = cache.get("F", {"uptown_waits": [], "downtown_waits": []})
    f_up = sorted(f_data["uptown_waits"])
    f_dn = sorted(f_data["downtown_waits"])

    sections = [
        {"letter": "D", "color": BDFM_ORANGE, "up": bd_up, "dn": bd_dn},
        {"letter": "F", "color": BDFM_ORANGE, "up": f_up, "dn": f_dn},
    ]

    for i, section in enumerate(sections):
        sy = i * SECTION_HEIGHT  # section top y

        # -- Draw circle logo --
        logo_r = 5
        logo_cx = logo_r + 1
        logo_cy = sy + SECTION_HEIGHT // 2
        draw.ellipse(
            [(logo_cx - logo_r, logo_cy - logo_r),
             (logo_cx + logo_r, logo_cy + logo_r)],
            fill=section["color"]
        )
        t_letter = Text(section["letter"], draw, font)
        draw.text(
            t_letter.coords(logo_cx - t_letter.width // 2 + 1, logo_cy - t_letter.height // 2),
            section["letter"], font=font, fill=(0, 0, 0)
        )

        # -- Filter out waits < MIN_WAIT --
        up_waits = [w for w in section["up"] if w >= MIN_WAIT]
        dn_waits = [w for w in section["dn"] if w >= MIN_WAIT]

        text_x = logo_cx + logo_r + 3  # start text to the right of the logo

        # -- Uptown row (top half of section) --
        up_str = ",".join(str(w) for w in up_waits[:3]) if up_waits else "-"
        t_up = Text(up_str, draw, font)
        up_y = sy + (SECTION_HEIGHT // 2 - t_up.height) // 2
        draw.text(t_up.coords(text_x, up_y), up_str, font=font, fill=YELLOW)

        # -- Downtown row (bottom half of section) --
        dn_str = ",".join(str(w) for w in dn_waits[:3]) if dn_waits else "-"
        t_dn = Text(dn_str, draw, font)
        dn_y = sy + SECTION_HEIGHT // 2 + (SECTION_HEIGHT // 2 - t_dn.height) // 2
        draw.text(t_dn.coords(text_x, dn_y), dn_str, font=font, fill=WHITE)

    # -- Dotted divider between D and F sections --
    divider_y = SECTION_HEIGHT
    for x in range(0, DISP_WIDTH, 2):
        draw.point((x, divider_y), fill=DIM)

    buf = BytesIO()
    img.save(buf, "WEBP")
    return buf.getvalue()


mta_app = App(
    id="mta",
    name="MTA",
    config=None,
    update_fn=mta_update,
    render_fn=mta_render,
    enabled=True,
    ttl=MTA_TTL,
)
