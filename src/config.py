"""
Configuration and constants for the IASC donor analytics tool.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present (for local development)
load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
DB_PATH = DATA_DIR / "donors.db"

# API configuration
def _get_secret(name: str) -> str | None:
    """Read a secret from Streamlit first, then from the environment."""
    try:
        import streamlit as st
        return st.secrets.get(name) or os.environ.get(name)
    except Exception:
        return os.environ.get(name)


ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
OPENAI_API_KEY = _get_secret("OPENAI_API_KEY")
OPENAI_BASE_URL = _get_secret("OPENAI_BASE_URL")

# Provider / model configuration
DEFAULT_PROVIDER = os.environ.get("LLM_PROVIDER", "claude")
DEFAULT_COMPARE_MODE = os.environ.get("LLM_COMPARE_MODE", "single")

CLAUDE_MODELS = {
    "claude-sonnet-4-20250514": "Sonnet (recommended)",
    "claude-haiku-4-5-20251001": "Haiku (faster, cheaper)",
}

OPENAI_MODELS = {
    "gpt-4.1": "GPT-4.1 (recommended)",
    "gpt-4.1-mini": "GPT-4.1 mini (faster, cheaper)",
}

BACKEND_OPTIONS = {
    "claude": "Claude",
    "openai": "OpenAI",
    "compare": "Compare both",
}

DEFAULT_CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

def get_models_for_provider(provider: str) -> dict[str, str]:
    """Return the available models for a provider."""
    if provider == "openai":
        return OPENAI_MODELS
    return CLAUDE_MODELS


def get_default_model_for_provider(provider: str) -> str:
    """Return the default model for a provider."""
    if provider == "openai":
        return DEFAULT_OPENAI_MODEL
    return DEFAULT_CLAUDE_MODEL


def get_api_key_for_provider(provider: str) -> str | None:
    """Return the configured API key for a provider."""
    if provider == "openai":
        return OPENAI_API_KEY
    return ANTHROPIC_API_KEY


def get_base_url_for_provider(provider: str) -> str | None:
    """Return an optional custom base URL for a provider."""
    if provider == "openai":
        return OPENAI_BASE_URL
    return None


# Backwards-compatible defaults used by older callers/tests.
# The app currently renders one provider at a time, so expose the selected
# provider's model list while defaulting to Claude for unknown modes.
if DEFAULT_PROVIDER == "openai":
    DEFAULT_MODEL = DEFAULT_OPENAI_MODEL
    AVAILABLE_MODELS = OPENAI_MODELS
else:
    DEFAULT_MODEL = DEFAULT_CLAUDE_MODEL
    AVAILABLE_MODELS = CLAUDE_MODELS


try:
    import streamlit as st  # noqa: F401
except Exception:
    pass

# Tool use limits
MAX_TOOL_CALLS_PER_TURN = 5  # prevent infinite loops
MAX_RESULTS_PER_QUERY = 20   # default limit for search results

# UI configuration
APP_TITLE = "IASC Donor Analytics"
APP_SUBTITLE = "AI-powered donor intelligence for the IASC and The Hedgehog Review"
