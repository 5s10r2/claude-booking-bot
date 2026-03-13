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

    # OSRM (map distance service)
    OSRM_API_KEY: str = ""

    # WhatsApp (defaults from env, not hardcoded tokens)
    WHATSAPP_ACCESS_TOKEN: Optional[str] = None
    WHATSAPP_VERIFY_TOKEN: str = "booking-bot-verify"

    # Models
    HAIKU_MODEL: str = "claude-haiku-4-5-20251001"
    SONNET_MODEL: str = "claude-sonnet-4-6"

    # Cost per million tokens (USD) — used by increment_session_cost
    COST_PER_MTK: dict = {
        "claude-haiku-4-5-20251001": {"in": 0.80,  "out": 4.00},
        "claude-sonnet-4-6":         {"in": 3.00,  "out": 15.00},
    }

    # API auth (set in .env; if empty, auth is disabled)
    API_KEY: Optional[str] = None

    # Web Intelligence
    TAVILY_API_KEY: Optional[str] = None  # Tavily search API key for web intelligence
    WEB_SEARCH_MAX_PER_CONVERSATION: int = 3  # max web searches per conversation

    # Feature flags
    KYC_ENABLED: bool = False  # Set KYC_ENABLED=true in env to re-enable Aadhaar verification
    PAYMENT_REQUIRED: bool = False  # Token payment before reservation. Toggle ON in admin panel when needed.
    DYNAMIC_SKILLS_ENABLED: bool = True  # Dynamic skill loading for broker agent. Set false to fall back to monolithic prompt.

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

    # WhatsApp message queuing + dedup
    WA_DEBOUNCE_SECONDS: float = 2.0   # wait this long after last message before processing batch
    WAMID_DEDUP_TTL: int = 86400       # 24h — covers Meta's duplicate delivery retry window
    WA_QUEUE_TTL: int = 300            # 5 min — pending message queue expiry safety net
    WA_PROCESSING_TTL: int = 120       # 2 min — per-user processing lock safety TTL

    model_config = {"env_file": ".env", "extra": "ignore", "env_ignore_empty": True}


settings = Settings()
