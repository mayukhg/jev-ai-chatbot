"""Application configuration loaded from environment variables and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_API_KEY = "your_openrouter_api_key_here"

SETUP_NOTICE = (
    "[SETUP NOTICE] .env initialized with placeholder credentials. "
    "Replace 'your_openrouter_api_key_here' with your active OpenRouter API key, "
    "or set MOCK_MODE=true for local mocking."
)


class Settings(BaseSettings):
    """Runtime settings for the Jev Decision Engine workbench."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = PLACEHOLDER_API_KEY
    openrouter_decisions_url: str = "https://openrouter.ai/api/alpha/decisions"
    jev_model: str = "typesafe/jev-1.14"
    port: int = 8000
    mock_mode: bool = False

    request_timeout_s: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    backoff_base_s: float = Field(default=0.5, ge=0)
    http_referer: str = "http://localhost:8000"
    app_title: str = "Jev Decision Engine Workbench"

    @property
    def has_placeholder_credentials(self) -> bool:
        """True when the API key is blank or still the template placeholder."""
        key = self.openrouter_api_key.strip()
        return not key or key == PLACEHOLDER_API_KEY

    @property
    def effective_mock_mode(self) -> bool:
        """The engine will simulate decisions locally when MOCK_MODE is set or no real key exists."""
        return self.mock_mode or self.has_placeholder_credentials

    @property
    def mock_reason(self) -> str | None:
        if self.mock_mode:
            return "mock_mode_enabled"
        if self.has_placeholder_credentials:
            return "placeholder_credentials"
        return None

    def setup_notice(self) -> str | None:
        """Returns the boot diagnostic banner when credentials are placeholders."""
        return SETUP_NOTICE if self.has_placeholder_credentials else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
