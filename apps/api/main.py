from contextlib import asynccontextmanager
from datetime import datetime
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, UUID4
from starlette.concurrency import run_in_threadpool
from uuid import UUID

if __package__:
    from .models.Device import DeviceManager
    from .models.Loader import AppLoader
    from .models.Playlist import Playlist
    from .models.Registry import app_registry
else:
    from models.Device import DeviceManager
    from models.Loader import AppLoader
    from models.Playlist import Playlist
    from models.Registry import app_registry


class FrameRequest(BaseModel):
    device_id: UUID4
    request_id: UUID


class LogEntry(BaseModel):
    message: str
    time: datetime


def create_server(
    *,
    registry=None,
    load_apps=True, 
    services=None
):
    registry = registry if registry is not None else app_registry
    manager = DeviceManager(playlist_factory=lambda: Playlist.default(registry=registry))
    loader = AppLoader(
        registry, services=services,
        exclude_files=("clock.py", "weather.py", "mta.py", "flights_overhead.py"),
    )

    @asynccontextmanager
    async def lifespan(app):
        if load_apps:
            await run_in_threadpool(loader.load_catalog)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.device_manager = manager
    app.state.app_registry = registry
    app.state.app_loader = loader
    
    app.add_middleware(
        CORSMiddleware, 
        allow_origins=["*"], 
        allow_credentials=True,
        allow_methods=["*"], 
        allow_headers=["*"],
    )

    @app.post("/api/current")
    def current(request: FrameRequest):
        # Unknown IDs create an in-memory device with the default playlist.
        # Provider calls and rendering run in the framework's thread pool.
        graphic = manager.handle_frame_request(
            str(request.device_id), str(request.request_id)
        )
        
        if graphic is None:
            raise HTTPException(
                status_code=503, 
                detail="No graphic is currently available.",
                headers={"Retry-After": "1"},
            )
        
        return Response(content=graphic, media_type="image/webp")


    @app.post("/api/logs", status_code=201)
    def logs(entry: LogEntry):
        with open("app.log", "a") as file:
            file.write(json.dumps({"message": entry.message, "time": entry.time.isoformat()}))
        return {"status": "logged"}

    return app


server = create_server()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:server", host="0.0.0.0", port=8000, reload=True)
