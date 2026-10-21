from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

from .Playlist import Playlist


def _validate_uuid(value: str, field: str) -> str:
    """Validate and normalize IDs so equivalent UUID spellings share state."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a valid UUID string.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UUID string.") from exc


class DeviceManager:

    device_id: str
    created_at: datetime
    owner_id: str | None
    last_request_at: datetime
    last_request_id: str
    playlist: Playlist

    def __init__(
        self,
        device_id: str,
        request_id: str,
        owner_id: str | None = None,
        *,
        playlist: Playlist | None = None,
    ):
        self.device_id = _validate_uuid(device_id, "device_id")
        self.last_request_id = _validate_uuid(request_id, "request_id")
        self.owner_id = (
            _validate_uuid(owner_id, "owner_id") if owner_id is not None else None
        )
        self.created_at = datetime.now(timezone.utc)
        self.last_request_at = self.created_at
        self.playlist = playlist if playlist is not None else Playlist()
        self._active_request_id: str | None = None
        self._request_lock = Lock()

    def handle_request(self, device_id: str, request_id: str) -> bytes | None:
        device_id = _validate_uuid(device_id, "device_id")
        request_id = _validate_uuid(request_id, "request_id")
        if device_id != self.device_id:
            raise ValueError("Incorrect device_id.")

        with self._request_lock:
            # These describe the latest accepted attempt, including a retry.
            self.last_request_at = datetime.now(timezone.utc)
            self.last_request_id = request_id

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
            return self.playlist.get_graphic()


class DeviceRegistry:

    def __init__(
        self,
        playlist_factory: Callable[[], Playlist] = Playlist,
    ):
        self._playlist_factory = playlist_factory
        self._devices: dict[str, DeviceManager] = {}
        self._lock = Lock()

    def get(self, device_id: str) -> DeviceManager | None:
        device_id = _validate_uuid(device_id, "device_id")
        with self._lock:
            return self._devices.get(device_id)

    def get_or_create(
        self,
        device_id: str,
        request_id: str,
        owner_id: str | None = None,
    ) -> DeviceManager:
        device_id = _validate_uuid(device_id, "device_id")
        request_id = _validate_uuid(request_id, "request_id")
        owner_id = (
            _validate_uuid(owner_id, "owner_id") if owner_id is not None else None
        )
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                device = DeviceManager(
                    device_id,
                    request_id,
                    owner_id,
                    playlist=self._playlist_factory(),
                )
                self._devices[device_id] = device
            elif owner_id is not None and owner_id != device.owner_id:
                raise ValueError("owner_id does not match the existing device.")
            return device
