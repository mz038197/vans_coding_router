import json
import re
from typing import Any

PREVIEW_MAX_LEN = 500
PREVIEW_TRUNCATED_SUFFIX = "...[preview truncated, see full log]"
_USER_REQUEST_PATTERN = re.compile(r"<userRequest>(.*?)</userRequest>", re.DOTALL | re.IGNORECASE)
_USER_QUERY_PATTERN = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL | re.IGNORECASE)
_ATTACHMENT_TAG_PATTERN = re.compile(r"<attachment\b[^>]*>.*?</attachment>", re.DOTALL | re.IGNORECASE)
_ATTACHMENT_SELF_PATTERN = re.compile(r"<attachment\b([^>/]*)/?>", re.IGNORECASE)
_NOISE_TAG_PATTERNS = (
    _ATTACHMENT_TAG_PATTERN,
    re.compile(r"<context>.*?</context>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<reminderInstructions>.*?</reminderInstructions>", re.DOTALL | re.IGNORECASE),
)
_ATTACHMENT_ID_PATTERN = re.compile(r"""id=["'](?:prompt:)?([^"']+)["']""", re.IGNORECASE)
_ATTACHMENT_PATH_PATTERN = re.compile(r"""filePath=["']([^"']+)["']""", re.IGNORECASE)


def flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            for key in ("text", "input_text", "output_text", "content"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value)
                    break
        if parts:
            return "\n".join(parts)
    if isinstance(content, dict):
        for key in ("text", "input_text", "output_text", "content"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return json.dumps(content, ensure_ascii=False)


def content_to_str(content: Any) -> str:
    return flatten_content(content)


def infer_log_role(msg: dict[str, Any]) -> str:
    role = msg.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip()

    msg_type = msg.get("type")
    if isinstance(msg_type, str):
        normalized = msg_type.strip().lower()
        if normalized == "message":
            nested_role = msg.get("role")
            if isinstance(nested_role, str) and nested_role.strip():
                return nested_role.strip()
            return "user"
        if normalized == "reasoning":
            return "reasoning"
        if "attachment" in normalized or msg.get("filePath") or msg.get("file_path"):
            return "attachment"
        if normalized in {"assistant", "user", "system", "tool"}:
            return normalized
        if normalized:
            return normalized

    if msg.get("filePath") or msg.get("file_path") or msg.get("id"):
        return "attachment"
    return "user"


def strip_copilot_noise(text: str) -> str:
    cleaned = text
    for pattern in _NOISE_TAG_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_attachment_label(text: str) -> str | None:
    for pattern in (_ATTACHMENT_ID_PATTERN, _ATTACHMENT_PATH_PATTERN):
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(1).strip()
        if not raw:
            continue
        filename = raw.replace("\\", "/").rsplit("/", 1)[-1]
        if filename:
            return f"[附件: {filename}]"
    match = _ATTACHMENT_SELF_PATTERN.search(text)
    if match:
        attrs = match.group(1)
        id_match = _ATTACHMENT_ID_PATTERN.search(attrs)
        if id_match:
            raw = id_match.group(1).strip()
            filename = raw.replace("\\", "/").rsplit("/", 1)[-1]
            if filename:
                return f"[附件: {filename}]"
    return None


def _attachment_label_from_message(msg: dict[str, Any]) -> str | None:
    for key in ("filePath", "file_path", "id"):
        value = msg.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        raw = value.strip()
        if key == "id" and raw.lower().startswith("prompt:"):
            raw = raw.split(":", 1)[1]
        filename = raw.replace("\\", "/").rsplit("/", 1)[-1]
        if filename:
            return f"[附件: {filename}]"
    return None


def messages_for_log(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logged: list[dict[str, Any]] = []
    for msg in messages:
        content = flatten_content(msg.get("content"))
        if not content.strip():
            content = _attachment_label_from_message(msg) or content
        entry: dict[str, Any] = {
            "role": infer_log_role(msg),
            "content": content,
        }
        for key in ("tool_calls", "tool_call_id", "tool_name"):
            if key in msg:
                entry[key] = msg[key]
        logged.append(entry)
    return logged


def _extract_tagged_user_text(content: str) -> str | None:
    for pattern in (_USER_REQUEST_PATTERN, _USER_QUERY_PATTERN):
        match = pattern.search(content)
        if not match:
            continue
        extracted = match.group(1).strip()
        if extracted:
            return extracted
    return None


def _truncate_preview(text: str) -> str:
    if len(text) <= PREVIEW_MAX_LEN:
        return text
    keep = PREVIEW_MAX_LEN - len(PREVIEW_TRUNCATED_SUFFIX)
    return text[:keep] + PREVIEW_TRUNCATED_SUFFIX


def _is_user_like_message(msg: dict[str, Any]) -> bool:
    role = msg.get("role", "")
    if role in {"user", "attachment", ""}:
        return True
    return role not in {"assistant", "reasoning", "system", "tool"}


def _preview_from_content(content: str) -> str | None:
    extracted = _extract_tagged_user_text(content)
    if extracted:
        return extracted

    cleaned = strip_copilot_noise(content)
    if cleaned:
        return cleaned

    attachment = extract_attachment_label(content)
    if attachment:
        return attachment
    return None


def build_message_preview(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""

    for msg in reversed(messages):
        if not _is_user_like_message(msg):
            continue
        content = content_to_str(msg.get("content"))
        preview = _preview_from_content(content)
        if preview:
            return _truncate_preview(preview)

    for msg in reversed(messages):
        content = content_to_str(msg.get("content")).strip()
        if content:
            return _truncate_preview(content)

    return ""


CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
RESPONSES_PATH = "/v1/responses"
IMAGES_PATH = "/v1/images"
AUDIO_SPEECH_PATH = "/v1/audio/speech"
RESPONSE_LOG_MAX_CHARS = 131_072
LOG_TRUNCATED_SUFFIX = "...[log truncated]"
TOOL_CALLS_ONLY_LABEL = "[僅 tool_calls]"


def truncate_log_text(text: str) -> tuple[str, bool]:
    if len(text) <= RESPONSE_LOG_MAX_CHARS:
        return text, False
    keep = RESPONSE_LOG_MAX_CHARS - len(LOG_TRUNCATED_SUFFIX)
    return text[:keep] + LOG_TRUNCATED_SUFFIX, True


def build_response_preview(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = content_to_str(msg.get("content")).strip()
        if content:
            return _truncate_preview(content)
    return ""


def _responses_output_list(response: dict[str, Any]) -> list[Any]:
    output = response.get("output")
    if isinstance(output, list):
        return output
    nested = response.get("response")
    if isinstance(nested, dict):
        nested_output = nested.get("output")
        if isinstance(nested_output, list):
            return nested_output
    return []


def _assistant_from_responses_output(output: list[Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message" or item.get("role") != "assistant":
            continue
        content = flatten_content(item.get("content")).strip()
        if content:
            truncated, _ = truncate_log_text(content)
            messages.append({"role": "assistant", "content": truncated})
    return messages


def _assistant_from_chat_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    if message.get("tool_calls"):
        return [{"role": "assistant", "content": TOOL_CALLS_ONLY_LABEL}]
    raw = message.get("content")
    if isinstance(raw, str):
        text = raw
    elif raw is None:
        text = ""
    else:
        text = flatten_content(raw)
    text = text.strip()
    if not text:
        return []
    truncated, _ = truncate_log_text(text)
    return [{"role": "assistant", "content": truncated}]


def extract_assistant_messages_for_log(response: dict[str, Any], api_endpoint: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []

    if api_endpoint == RESPONSES_PATH:
        return _assistant_from_responses_output(_responses_output_list(response))

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    first = choices[0]
    if not isinstance(first, dict):
        return []
    message = first.get("message")
    if not isinstance(message, dict):
        delta = first.get("delta")
        if isinstance(delta, dict):
            return _assistant_from_chat_message({"content": delta.get("content") or ""})
        return []
    return _assistant_from_chat_message(message)


def truncate_assistant_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    truncated_messages: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            truncated_messages.append(msg)
            continue
        content = content_to_str(msg.get("content"))
        text, _ = truncate_log_text(content)
        truncated_messages.append({**msg, "content": text})
    return truncated_messages
