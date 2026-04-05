import os

# Global defaults (used as fallback when per-agent values are not set)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct")

# Per-agent API keys (fall back to global OPENROUTER_API_KEY)
ORCHESTRATOR_API_KEY = os.getenv("ORCHESTRATOR_API_KEY", OPENROUTER_API_KEY)
WATCHMAN_API_KEY = os.getenv("WATCHMAN_API_KEY", OPENROUTER_API_KEY)
SHIELD_API_KEY = os.getenv("SHIELD_API_KEY", OPENROUTER_API_KEY)
SCRIBE_API_KEY = os.getenv("SCRIBE_API_KEY", OPENROUTER_API_KEY)

# Per-agent base URLs (fall back to global LLM_BASE_URL)
ORCHESTRATOR_BASE_URL = os.getenv("ORCHESTRATOR_BASE_URL", LLM_BASE_URL)
WATCHMAN_BASE_URL = os.getenv("WATCHMAN_BASE_URL", LLM_BASE_URL)
SHIELD_BASE_URL = os.getenv("SHIELD_BASE_URL", LLM_BASE_URL)
SCRIBE_BASE_URL = os.getenv("SCRIBE_BASE_URL", LLM_BASE_URL)

# Service URLs
WATCHMAN_URL = os.getenv("WATCHMAN_URL", "http://watchman:6001")
SHIELD_URL = os.getenv("SHIELD_URL", "http://shield:6002")
SCRIBE_URL = os.getenv("SCRIBE_URL", "http://scribe:6003")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/app/workspace")
