import json
import re
from typing import Any

PREVIEW_MAX_LEN = 500
PREVIEW_TRUNCATED_SUFFIX = "...[preview truncated, see full log]"
_USER_REQUEST_PATTERN = re.compile(r"<userRequest>(.*?)</userRequest>", re.DOTALL | re.IGNORECASE)
_USER_QUERY_PATTERN = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL | re.IGNORECASE)


def content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def messages_for_log(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logged: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {
            "role": msg.get("role", ""),
            "content": content_to_str(msg.get("content")),
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


def build_message_preview(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = content_to_str(msg.get("content"))
        extracted = _extract_tagged_user_text(content)
        if extracted:
            return _truncate_preview(extracted)

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = content_to_str(msg.get("content")).strip()
        if content:
            return _truncate_preview(content)

    return _truncate_preview(content_to_str(messages[-1].get("content")))
