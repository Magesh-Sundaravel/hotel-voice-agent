"""Application settings, loaded from environment / .env."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the hotel voice agent backend."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    elevenlabs_api_key: str = ""
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    telnyx_api_key: str = ""
    # Shared secret ElevenLabs sends in X-Webhook-Secret on tool and /llm calls.
    webhook_secret: str = ""
    # Supabase session pooler connection string (Connect -> Session pooler).
    database_url: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    # The Gmail account the refresh token belongs to; confirmations come from it.
    gmail_sender: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"
    aws_region: str = ""
    log_level: str = "INFO"
