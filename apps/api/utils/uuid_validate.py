from uuid import UUID

def _validate_uuid(value: str, field: str) -> str:
    """Validate and normalize IDs so equivalent UUID spellings share state."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a valid UUID string.")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UUID string.") from exc