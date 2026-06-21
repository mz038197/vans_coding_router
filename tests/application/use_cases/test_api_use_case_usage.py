from src.application.use_cases.api_use_case import (
    _SseUsageTracker,
    _usage_from_response,
    _usage_from_sse_event,
)


def test_usage_from_response_reads_nested_responses_usage():
    payload = {
        "type": "response.completed",
        "response": {
            "usage": {
                "input_tokens": 120,
                "output_tokens": 45,
                "total_tokens": 165,
            }
        },
    }
    assert _usage_from_response(payload) == {
        "prompt_tokens": 120,
        "completion_tokens": 45,
        "total_tokens": 165,
    }


def test_usage_from_sse_event_reads_response_completed():
    event = (
        'event: response.completed\n'
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}}\n'
    )
    assert _usage_from_sse_event(event) == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }


def test_sse_usage_tracker_buffers_split_events():
    tracker = _SseUsageTracker()
    part_a = (
        b'event: response.completed\n'
        b'data: {"type":"response.completed","response":{"usage":{"input_tokens":8,"output_tokens":2,"total_tokens":10}}}\n\n'
    )
    tracker.feed(part_a[:30])
    assert tracker.usage == {}
    tracker.feed(part_a[30:])
    assert tracker.usage["total_tokens"] == 10


def test_sse_usage_tracker_reads_chat_finish_usage_chunk():
    tracker = _SseUsageTracker()
    tracker.feed(
        b'data: {"object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":3,"completion_tokens":7,"total_tokens":10}}\n\n'
    )
    assert tracker.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 7,
        "total_tokens": 10,
    }
