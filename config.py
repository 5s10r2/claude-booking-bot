from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Anthropic
    ANTHROPIC_API_KEY: str

    # Redis — prefer URL (Render provides this), fallback to host/port
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None

    # PostgreSQL — prefer URL (Render provides this), fallback to individual params
    DATABASE_URL: Optional[str] = None
    DB_HOST: str = "localhost"
    DB_NAME: str = "booking_bot"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_PORT: int = 5432

    # Rentok API
    RENTOK_API_BASE_URL: str = "https://apiv2.rentok.com"

    # WhatsApp (defaults from env, not hardcoded tokens)
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: str = "booking-bot-verify"

    # Models
    HAIKU_MODEL: str = "claude-haiku-4-5-20251001"
    SONNET_MODEL: str = "claude-sonnet-4-6"

    # API auth (set in .env; if empty, auth is disabled)
    API_KEY: Optional[str] = None

    # Feature flags
    KYC_ENABLED: bool = False  # Set KYC_ENABLED=true in env to re-enable Aadhaar verification

    # Agent settings
    MAX_AGENT_ITERATIONS: int = 15
    CONVERSATION_HISTORY_LIMIT: int = 20
    CONVERSATION_TTL_SECONDS: int = 86400  # 24 hours

    # Conversation summarization
    SUMMARIZE_THRESHOLD: int = 30       # trigger summarization at this message count
    SUMMARIZE_KEEP_RECENT: int = 10     # keep this many recent messages verbatim

    # Rate limiting (per sliding window)
    RATE_LIMIT_USER_PER_MINUTE: int = 6       # max messages per user per minute
    RATE_LIMIT_USER_PER_HOUR: int = 30        # max messages per user per hour
    RATE_LIMIT_GLOBAL_PER_MINUTE: int = 100   # max messages across all users per minute

    model_config = {"env_file": ".env", "extra": "ignore", "env_ignore_empty": True}


settings = Settings()
