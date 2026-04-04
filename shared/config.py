import os

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen-2.5-72b-instruct")
WATCHMAN_URL = os.getenv("WATCHMAN_URL", "http://watchman:6001")
SHIELD_URL = os.getenv("SHIELD_URL", "http://shield:6002")
SCRIBE_URL = os.getenv("SCRIBE_URL", "http://scribe:6003")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/app/workspace")
