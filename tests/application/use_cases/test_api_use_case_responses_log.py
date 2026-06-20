from src.application.use_cases.api_use_case import _responses_input_for_log
from src.infrastructure.logging.message_preview import (
    build_message_preview,
    flatten_content,
    infer_log_role,
    messages_for_log,
)


def test_flatten_content_output_text_array():
    content = [{"type": "output_text", "text": "Hello **world**"}]
    assert flatten_content(content) == "Hello **world**"


def test_messages_for_log_infers_responses_roles():
    raw = [
        {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "thinking"}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hello back"}],
        },
    ]
    logged = messages_for_log(raw)
    assert logged[0]["role"] == "reasoning"
    assert logged[1]["role"] == "user"
    assert logged[1]["content"] == "hi"
    assert logged[2]["role"] == "assistant"
    assert logged[2]["content"] == "hello back"


def test_build_message_preview_from_attachment_with_user_request():
    attachment = (
        '\n<attachment id="prompt:SKILL.md" filePath="c:\\\\Users\\\\dev\\\\SKILL.md"></attachment>'
        "<userRequest>幫我做簡報</userRequest>"
    )
    messages = messages_for_log([{"type": "message", "role": "user", "content": attachment}])
    preview = build_message_preview(messages)
    assert preview == "幫我做簡報"


def test_build_message_preview_attachment_only():
    attachment = '<attachment id="prompt:SKILL.md" filePath="c:\\\\Users\\\\dev\\\\SKILL.md"></attachment>'
    messages = messages_for_log([{"type": "message", "role": "user", "content": attachment}])
    preview = build_message_preview(messages)
    assert preview == "[附件: SKILL.md]"


def test_build_message_preview_responses_input_pipeline():
    body = {
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            '<attachment id="prompt:SKILL.md"></attachment>'
                            "<userRequest>建立 Ollama 簡報</userRequest>"
                        ),
                    }
                ],
            }
        ]
    }
    messages = messages_for_log(_responses_input_for_log(body))
    preview = build_message_preview(messages)
    assert preview == "建立 Ollama 簡報"
    assert infer_log_role(body["input"][0]) == "user"
