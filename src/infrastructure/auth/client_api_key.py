from __future__ import annotations

VCR_KEY_PREFIX = "vcr_sk_"


def normalize_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    return api_key.strip()


def classify_client_api_key(api_key: str) -> str | None:
    """Return a failure reason code, or None to defer to DB verification."""
    api_key = normalize_api_key(api_key)
    if not api_key:
        return "missing"
    if api_key in ("${apiKey}", "${input:chat.lm.secret}") or api_key.startswith("${"):
        return "unresolved_placeholder"
    if api_key.startswith("eyJ") and api_key.count(".") >= 2:
        return "copilot_token"
    return None
