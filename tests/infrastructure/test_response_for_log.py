from src.application.use_cases.api_use_case import _SseStreamTracker
from src.infrastructure.logging.message_preview import (
    CHAT_COMPLETIONS_PATH,
    LOG_TRUNCATED_SUFFIX,
    RESPONSES_PATH,
    RESPONSE_LOG_MAX_CHARS,
    build_response_preview,
    extract_assistant_messages_for_log,
    messages_for_log,
    truncate_log_text,
)


def test_extract_assistant_from_chat_completion():
    response = {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello back", "reasoning_content": "hidden"},
                "finish_reason": "stop",
            }
        ]
    }
    logged = messages_for_log(extract_assistant_messages_for_log(response, CHAT_COMPLETIONS_PATH))
    assert logged == [{"role": "assistant", "content": "hello back"}]


def test_extract_assistant_ignores_responses_reasoning():
    response = {
        "output": [
            {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "thinking"}]},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            },
        ]
    }
    logged = messages_for_log(extract_assistant_messages_for_log(response, RESPONSES_PATH))
    assert logged == [{"role": "assistant", "content": "done"}]


def test_build_response_preview_uses_last_assistant():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    assert build_response_preview(messages) == "second"


def test_truncate_log_text_at_128kb():
    text = "x" * (RESPONSE_LOG_MAX_CHARS + 10)
    truncated, was_truncated = truncate_log_text(text)
    assert was_truncated is True
    assert truncated.endswith(LOG_TRUNCATED_SUFFIX)
    assert len(truncated) == RESPONSE_LOG_MAX_CHARS


def test_sse_stream_tracker_accumulates_chat_content():
    tracker = _SseStreamTracker(CHAT_COMPLETIONS_PATH)
    tracker.feed(
        b'data: {"choices":[{"index":0,"delta":{"content":"hel"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"content":"lo"}}]}\n\n'
    )
    assert tracker.assistant_messages == [{"role": "assistant", "content": "hello"}]


def test_sse_stream_tracker_reads_responses_completed_output():
    tracker = _SseStreamTracker(RESPONSES_PATH)
    tracker.feed(
        b'event: response.completed\n'
        b'data: {"type":"response.completed","response":{"output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"stream done"}]}]}}\n\n'
    )
    assert tracker.assistant_messages == [{"role": "assistant", "content": "stream done"}]
