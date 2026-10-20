from datetime import datetime, timezone
from Playlist import Playlist
from uuid import uuid4


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
        owner_id: str | None = None
    ):
        # TODO: Check if device_id, owner_id, and request_id are valid UUID

        self.device_id = device_id
        self.created_at = datetime.now(timezone.utc)
        self.owner_id = owner_id

        self.last_request_at = datetime.now(timezone.utc)
        self.last_request_id = request_id

    def handle_request(self, device_id: str, request_id: str) -> bytes | None:
        if device_id != self.device_id:
            raise Exception("Incorrect device_id.")

        if request_id != self.last_request_id:
            self.playlist.advance_app()

        return self.playlist.get_graphic()

            


