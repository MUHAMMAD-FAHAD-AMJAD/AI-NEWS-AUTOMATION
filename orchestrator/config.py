"""
orchestrator/config.py
-----------------------
Loads all required environment variables and validates they are present.

SECURITY RULES enforced here:
  - All secrets come from env vars ONLY — never hardcoded
  - Missing secrets cause an immediate hard crash with a clear error
  - No secret values are ever logged or printed
"""

import os
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when required environment variables are missing at startup."""
    pass


@dataclass
class Config:
    supabase_url: str
    supabase_key: str
    groq_api_key: str
    mistral_api_key: str
    openrouter_api_key: str
    gemini_api_key: str
    whatsapp_channel_jid: str
    max_posts_per_day: int = 5
    poll_lookback_hours: int = 24
    similarity_threshold: float = 0.75

    def __repr__(self) -> str:
        """Safe repr — never exposes secret values."""
        return (
            f"Config("
            f"supabase_url={self.supabase_url[:30]}..., "
            f"max_posts_per_day={self.max_posts_per_day}, "
            f"poll_lookback_hours={self.poll_lookback_hours}, "
            f"similarity_threshold={self.similarity_threshold}"
            f")"
        )


def load_config() -> Config:
    """
    Load and validate all required environment variables.

    Raises ConfigError immediately if any required variable is missing.
    This is intentional — the pipeline must not proceed with partial config.

    Returns:
        Config: Validated configuration dataclass.

    Raises:
        ConfigError: If one or more required environment variables are absent.
    """
    required_vars = [
        'SUPABASE_URL',
        'SUPABASE_KEY',
        'GROQ_API_KEY',
        'MISTRAL_API_KEY',
        'OPENROUTER_API_KEY',
        'GEMINI_API_KEY',
        'WHATSAPP_CHANNEL_JID',
    ]

    missing = [k for k in required_vars if not os.environ.get(k)]
    if missing:
        raise ConfigError(
            f"STARTUP FAILED — Missing required environment variables: {missing}\n"
            f"Set all secrets in GitHub Actions Secrets or your local .env file."
        )

    return Config(
        supabase_url=os.environ['SUPABASE_URL'],
        supabase_key=os.environ['SUPABASE_KEY'],
        groq_api_key=os.environ['GROQ_API_KEY'],
        mistral_api_key=os.environ['MISTRAL_API_KEY'],
        openrouter_api_key=os.environ['OPENROUTER_API_KEY'],
        gemini_api_key=os.environ['GEMINI_API_KEY'],
        whatsapp_channel_jid=os.environ['WHATSAPP_CHANNEL_JID'],
    )
