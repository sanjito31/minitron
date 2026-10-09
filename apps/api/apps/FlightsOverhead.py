from models.App import App
from config import settings
from PIL import Image
from io import BytesIO
import math
import requests
from utils.draw import Text, DISP_HEIGHT, DISP_WIDTH
from PIL import Image, ImageDraw, ImageFont

FLIGHTS_OVERHEAD_TTL = 120 #seconds


def flights_overhead_update(config: dict) -> dict | None:

    url = str(config.get("OPENSKY_URL"))

    resp = requests.get(url)
    resp_json = resp.json()
    req_time = resp_json["time"]

    if not resp_json["states"] or resp.status_code != 200: return None
    
    flights = []
    for flight in resp_json["states"]:
            home = (float(settings.LON), float(settings.LAT))
            plane = (flight[5], flight[6])
            altitude = flight[13]
            if altitude is None:
                    continue

            flight.append(bearing(home, plane))
            flight.append(coord_dist(home, plane, altitude))
            flights.append(flight)

    flights = sorted(flights.copy(), key=lambda x: x[-1])
    # print(flights)

    # ADSDB_AIR_URL = f"https://api.adsbdb.com/v0/aircraft/{flights[0][0]}"

    flight_info = None
    flight_obj = None
    for flight in flights:
        ADSDB_CALLSIGN_URL = f"https://api.adsbdb.com/v0/callsign/{flight[1].strip()}"
        resp = requests.get(ADSDB_CALLSIGN_URL).json()
        # print(resp)
        if isinstance(resp.get("response"), dict):
                flight_obj = flight
                flight_info = resp
                break

    
    if flight_info is not None and flight_obj is not None:    
        return {
                "flight_no": flight_info["response"]["flightroute"]["callsign"],
                "airline": flight_info["response"]["flightroute"]["airline"]["name"],
                "distance": flight_obj[-1],
                "bearing": flight_obj[-2],
                "origin": {
                        "code": flight_info["response"]["flightroute"]["origin"]["iata_code"],
                        "name": flight_info["response"]["flightroute"]["origin"]["name"],
                        "city": flight_info["response"]["flightroute"]["origin"]["municipality"],
                        "country": flight_info["response"]["flightroute"]["origin"]["country_name"]
                },
                "destination": {
                        "code": flight_info["response"]["flightroute"]["destination"]["iata_code"],
                        "name": flight_info["response"]["flightroute"]["destination"]["name"],
                        "city": flight_info["response"]["flightroute"]["destination"]["municipality"],
                        "country": flight_info["response"]["flightroute"]["destination"]["country_name"]
                }
        }
    else:
            return None



def flights_overhead_render(cache: dict) -> bytes:
    if cache is None:
        return draw_flight(flights={
            "flight_no": "",
            "airline": "",
            "origin": {"code": "---"},
            "destination": {"code": "---"},
        })
    return draw_flight(flights=cache)

LOGO_SIZE = 16
LOGO_DIR = "./assets/airline_logos"
AIRLINE_LOGOS = {
    "american": f"{LOGO_DIR}/aa.jpg",
    "delta": f"{LOGO_DIR}/delta.jpg",
    "united": f"{LOGO_DIR}/united.png",
    "southwest": f"{LOGO_DIR}/southwest.jpg",
    "spirit": f"{LOGO_DIR}/spirit.jpg",
}
DEFAULT_LOGO = f"{LOGO_DIR}/generic_plane.png"

def draw_flight(flights: dict,
                    width: int = DISP_WIDTH,
                    height: int = DISP_HEIGHT,
                    fontsize: int = 8,
                    bg: tuple = (0, 0, 0),
                    fg: tuple = (255, 255, 255),
                ):

    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("./fonts/Minecraft.ttf", fontsize, layout_engine=ImageFont.Layout.BASIC)
    except Exception as e:
        font = ImageFont.load_default()

    margin = 2

    # -- Top left: airline logo --
    airline_name = flights["airline"].lower()
    logo_path = DEFAULT_LOGO
    for keyword, path in AIRLINE_LOGOS.items():
        if keyword in airline_name:
            logo_path = path
            break
    try:
        logo = Image.open(logo_path).convert("RGBA").convert("RGB")
        logo = logo.resize((LOGO_SIZE, LOGO_SIZE))
        img.paste(logo, (margin, margin))
    except Exception:
        pass

    logo_right = margin + LOGO_SIZE + 2  # text starts after the logo

    # -- Top right: origin → dest --
    route_str = f"{flights['origin']['code']}>{flights['destination']['code']}"
    route = Text(route_str, draw, font)
    draw.text(route.coords(width - margin - route.width, margin), route_str, font=font, fill=fg)

    # -- Bottom: airline name --
    airline = Text(flights["airline"], draw, font)
    draw.text(airline.coords(margin, height - margin - airline.height), airline.text, font=font, fill=fg)

    buf = BytesIO()
    img.save(buf, "WEBP")
    return buf.getvalue()


def coord_dist(loc1, loc2, alt):
    METERS_PER_DEG = 111111
    dLat = (loc2[0] - loc1[0]) * METERS_PER_DEG
    dLon = (loc2[1] - loc1[1]) * METERS_PER_DEG * math.cos(loc1[0] * math.pi / 180)
    dist2d = math.sqrt(dLat**2 + dLon**2)
    if alt is None:
        return dist2d
    return math.sqrt(dist2d**2 + alt**2)    

def bearing(loc1, loc2):
    dLat = (loc2[0] - loc1[0]) * 111111
    dLon = (loc2[1] - loc1[0]) * 111111 * math.cos(math.radians(loc1[0]))
    angle = math.degrees(math.atan2(dLon, dLat))
    return angle % 360  

flights_app = App(
    id="flights_overhead",
    name="Flights Overhead",
    enabled=True,
    update_fn=flights_overhead_update,
    render_fn=flights_overhead_render,
    ttl=FLIGHTS_OVERHEAD_TTL,
    config={
        "OPENSKY_URL": f"https://opensky-network.org/api/states/all?lamin={settings.LATMIN}&lomin={settings.LOMIN}&lamax={settings.LATMAX}&lomax={settings.LOMAX}",
    }
)