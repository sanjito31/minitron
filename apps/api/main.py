from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import json

from models.Carousel import AppCarousel
from apps import app_registry


server = FastAPI()
PORT = 8000

server.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)




@server.get("/api/test")
async def test():
    from apps import weather_app

    weather_app.update()
    return Response(content=weather_app.render(), media_type="image/webp")


# ----------------------------------------------
# Main Current Frame Endpoint
# ----------------------------------------------
carousel = AppCarousel(app_registry)

@server.get("/api/current")
async def current():
    return Response(content=carousel.render_current(), media_type="image/webp")




LOG_FILE = "app.log"

class LogEntry(BaseModel):
    message: str
    time: datetime


@server.post("/api/logs", status_code=201)
async def logs(entry: LogEntry):
    with open(LOG_FILE, "a") as f:
        log = {
            "message": entry.message,
            "time": entry.time.isoformat()
        }
        f.write(json.dumps(log))
    return {"status": "logged"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:server", host="0.0.0.0", port=PORT, reload=True)
