from __future__ import annotations

from typing import Any

VSRouter_REQUEST_HEADERS: dict[str, str] = {
    "Authorization": "Bearer ${apiKey}",
}

MODEL_PATCH_KEYS: tuple[str, ...] = (
    "requestHeaders",
    "thinking",
    "reasoningEffortFormat",
    "zeroDataRetentionEnabled",
    "supportsReasoningEffort",
    "toolCalling",
    "vision",
    "maxInputTokens",
    "maxOutputTokens",
)


def patch_model_from_template(existing: dict[str, Any], template: dict[str, Any]) -> None:
    for key in MODEL_PATCH_KEYS:
        if key not in existing and key in template:
            existing[key] = template[key]
