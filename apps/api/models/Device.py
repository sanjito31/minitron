from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock

if __package__ == "models":
    from utils import _validate_uuid
else:
    from ..utils import _validate_uuid

from .Playlist import Playlist


class Device:

    def __init__(
        self,
        device_id: str,
        owner_id: str | None = None,
        *,
        playlist: Playlist | None = None,
    ):
        self.device_id = _validate_uuid(device_id, "device_id")
        self.owner_id = (
            _validate_uuid(owner_id, "owner_id") if owner_id is not None else None
        )
        self.playlist = playlist if playlist is not None else Playlist.default()
        
        self._created_at = datetime.now(timezone.utc)

        self.last_request_id: str | None = None
        self.last_request_at: datetime | None = None
        self._active_request_id: str | None = None
        self._lock = Lock()


    def handle_request(
        self, 
        device_id: str, 
        request_id: str
    ) -> bytes | None:
        device_id = _validate_uuid(device_id, "device_id")
        request_id = _validate_uuid(request_id, "request_id")
        if device_id != self.device_id:
            raise ValueError("Incorrect device_id.")

        with self._lock:
            if self.playlist.get_num_apps() == 0:
                return None

            if (
                self._active_request_id is not None
                and request_id != self._active_request_id
            ):
                self.playlist.advance_app()

            # Record selection before rendering: even if rendering fails or the
            # response is lost, retrying this ID must stay on the selected app.
            self._active_request_id = request_id
            graphic = self.playlist.get_graphic()
            if graphic is not None:
                # Record success only after a graphic has been produced.
                self.last_request_id = request_id
                self.last_request_at = datetime.now(timezone.utc)
            return graphic


class DeviceManager:

    def __init__(
        self,
        playlist_factory: Callable[[], Playlist] = Playlist.default,
    ):
        self._playlist_factory = playlist_factory
        self._devices: dict[str, Device] = {}
        self._lock = Lock()


    def get(self, device_id: str) -> Device | None:
        device_id = _validate_uuid(device_id, "device_id")
        with self._lock:
            return self._devices.get(device_id)


    def get_or_create(
        self,
        device_id: str,
        owner_id: str | None = None,
    ) -> Device:
        device_id = _validate_uuid(device_id, "device_id")
        owner_id = (
            _validate_uuid(owner_id, "owner_id") if owner_id is not None else None
        )
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                device = Device(
                    device_id,
                    owner_id,
                    playlist=self._playlist_factory(),
                )
                self._devices[device_id] = device
            elif owner_id is not None and owner_id != device.owner_id:
                raise ValueError("owner_id does not match the existing device.")
            return device

    def handle_frame_request(
        self,
        device_id: str,
        request_id: str
    )-> bytes | None:
        device_id = _validate_uuid(device_id, "device_id")
        request_id = _validate_uuid(request_id, "request_id")

        device = self.get_or_create(device_id)
        graphics = device.handle_request(device_id, request_id)

        return graphics if graphics else None
