from pydantic_settings import BaseSettings, SettingsConfigDict


# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------
class Settings(BaseSettings):
    """
    Application settings managed by Pydantic.
    Reads from environment variables and/or .env file.
    """

    # Weather App
    OPEN_WEATHER_API_KEY: str
    LAT: str
    LON: str

    LOMAX: float
    LOMIN: float
    LATMIN: float
    LATMAX: float

    # Spotify
    SPOTIFY_CLIENT_ID: str | None
    SPOTIFY_CLIENT_SECRET: str | None
    SPOTIFY_REDIRECT_URI: str | None


    
    # Config to read from .env file if available
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        extra="ignore"
        )

settings = Settings() # type: ignore