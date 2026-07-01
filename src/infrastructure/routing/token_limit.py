from __future__ import annotations


def resolve_chat_output_token_limit(
    max_tokens: int | None,
    max_completion_tokens: int | None,
) -> int | None:
    if max_completion_tokens is not None:
        return max_completion_tokens
    return max_tokens
