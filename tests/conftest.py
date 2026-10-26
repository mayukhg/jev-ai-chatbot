import pytest

from app.core.config import Settings


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(_env_file=None, mock_mode=True)


@pytest.fixture
def live_settings() -> Settings:
    return Settings(_env_file=None, openrouter_api_key="sk-or-test-key", mock_mode=False, backoff_base_s=0)
