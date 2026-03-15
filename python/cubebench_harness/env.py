from __future__ import annotations

import os


def require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {var_name}")
    return value


def require_google_api_key() -> str:
    value = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not value:
        raise RuntimeError(
            "Missing required environment variable: GOOGLE_API_KEY or GEMINI_API_KEY"
        )
    return value
