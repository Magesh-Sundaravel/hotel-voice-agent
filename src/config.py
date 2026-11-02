"""Application settings, loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the hotel voice agent backend."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    elevenlabs_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    telnyx_api_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""
    aws_region: str = ""
