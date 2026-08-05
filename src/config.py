"""Runtime configuration.

Model names live here, in source, NOT in .env — README section 9 requires the
model name to be declared in code and mirrored into logging/metadata.json so it
can be graded. Only credentials and endpoints come from the environment.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
INPUT_DIR = REPO_ROOT / "input"
OUTPUT_DIR = REPO_ROOT / "output"
LOG_DIR = REPO_ROOT / "logging"
CACHE_DIR = REPO_ROOT / ".llm_cache"

POLICY_VERSION = "EC_POLICY_V1"
COHORT = "K3"
CURRENCY = "BRL"

# --- Model registry -------------------------------------------------------
# Every entry must be <= 10B parameters (README section 9).
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.1-8b-instant",
        "parameter_size": "8B",
        "api_key_env": "GROQ_API_KEY",
    },
    "lmstudio": {
        "base_url": os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"),
        "model": "qwen/qwen3-1.7b",
        "parameter_size": "1.7B",
        "api_key_env": None,
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model": "ministral-3-8b-25-12",
        "parameter_size": "8B",
        "api_key_env": "MISTRAL_API_KEY",
    },
}


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader — avoids a python-dotenv dependency."""
    path = path or (REPO_ROOT / ".env")
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def active_provider() -> dict:
    load_dotenv()
    name = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    if name not in PROVIDERS:
        raise ValueError(f"unknown LLM_PROVIDER={name!r}; pick one of {sorted(PROVIDERS)}")
    cfg = dict(PROVIDERS[name])
    cfg["name"] = name
    cfg["api_key"] = os.environ.get(cfg["api_key_env"], "") if cfg["api_key_env"] else ""
    if cfg["api_key_env"] and not cfg["api_key"]:
        raise RuntimeError(f"{cfg['api_key_env']} is empty — fill it in .env")
    return cfg


# --- Output limits (README section 6) — exceeding these is a hard gate ----
MAX_ENTITY_IDS = 5
MAX_EVIDENCE = 10
MAX_ROOT_CAUSES = 3
MAX_RESPONSIBLE_PARTIES = 3
MAX_ACTIONS = 5
