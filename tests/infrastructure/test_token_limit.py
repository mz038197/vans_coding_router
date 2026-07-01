import pytest

from src.infrastructure.routing.token_limit import resolve_chat_output_token_limit


@pytest.mark.parametrize(
    ("max_tokens", "max_completion_tokens", "expected"),
    [
        (None, 256, 256),
        (128, 256, 256),
        (128, None, 128),
        (None, None, None),
    ],
)
def test_resolve_chat_output_token_limit(max_tokens, max_completion_tokens, expected):
    assert (
        resolve_chat_output_token_limit(max_tokens, max_completion_tokens) == expected
    )
