from datetime import datetime

class DeviceConfig:
    device_id: str
    created_at: datetime
    last_seen_at: datetime


class DeviceRequest:
    last_request_at: datetime
    last_request_id: str
    cached_webp_bytes: bytes
    cached_webp_ttl_ms: int


class DeviceManager:
    config: DeviceConfig
    request: DeviceRequest
    