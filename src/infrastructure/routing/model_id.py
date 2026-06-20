from __future__ import annotations

from src.domain.errors import InvalidModelIdError

_FORMAT_HINT = "模型 ID 須使用 provider@model 格式，例如 openrouter@anthropic/claude-sonnet-4"


def parse_model_id(model: str, known_providers: set[str]) -> tuple[str, str]:
    if "@" not in model:
        raise InvalidModelIdError(_FORMAT_HINT)

    provider, _, upstream = model.partition("@")
    if not provider:
        raise InvalidModelIdError(_FORMAT_HINT)
    if provider not in known_providers:
        raise InvalidModelIdError(f"未知的 provider：{provider}")
    if not upstream:
        raise InvalidModelIdError("模型 ID 缺少 @ 後的 upstream model")

    return provider, upstream


def format_model_id(provider: str, upstream_id: str) -> str:
    return f"{provider}@{upstream_id}"
