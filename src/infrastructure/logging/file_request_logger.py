import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from pytz import timezone

TZ_UTC8 = timezone("Asia/Taipei")
PREVIEW_MAX_LEN = 500
PREVIEW_TRUNCATED_SUFFIX = "...[preview truncated, see full log]"
_USER_REQUEST_PATTERN = re.compile(r"<userRequest>(.*?)</userRequest>", re.DOTALL | re.IGNORECASE)
_USER_QUERY_PATTERN = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL | re.IGNORECASE)


def _content_to_str(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _messages_for_log(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logged: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {
            "role": msg.get("role", ""),
            "content": _content_to_str(msg.get("content")),
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


def _build_message_preview(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = _content_to_str(msg.get("content"))
        extracted = _extract_tagged_user_text(content)
        if extracted:
            return _truncate_preview(extracted)

    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = _content_to_str(msg.get("content")).strip()
        if content:
            return _truncate_preview(content)

    return _truncate_preview(_content_to_str(messages[-1].get("content")))


def _count_total_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(_content_to_str(msg.get("content"))) for msg in messages)


def _normalize_client_ip(client_ip: str | None) -> str:
    if not client_ip:
        return "unknown"
    return client_ip.strip() or "unknown"


def _mask_api_key(api_key: str) -> str:
    return api_key[:20] + "..." if len(api_key) > 20 else api_key


def _item_search_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("message_preview", ""))]
    for msg in item.get("messages") or []:
        parts.append(str(msg.get("content", "")))
    return "\n".join(parts).lower()


class FileRequestLogger:
    def __init__(self, log_dir: Path | None = None):
        if log_dir is None:
            log_dir = Path.home() / ".vans_coding_router" / "logs"
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "full").mkdir(parents=True, exist_ok=True)

    def _get_log_file_path(self, date_str: str | None = None) -> Path:
        if date_str is None:
            date_str = datetime.now(TZ_UTC8).strftime("%Y%m%d")
        return self.log_dir / f"log_{date_str}.log"

    def _get_full_log_file_path(self, date_str: str | None = None) -> Path:
        if date_str is None:
            date_str = datetime.now(TZ_UTC8).strftime("%Y%m%d")
        return self.log_dir / "full" / f"log_{date_str}.log"

    def log_validation_result(
        self,
        teacher_name: str | None,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        is_valid: bool,
        client_ip: str | None = None,
    ) -> None:
        validation_result = "通過" if is_valid else "拒絕"
        try:
            now = datetime.now(TZ_UTC8)
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            date_str = now.strftime("%Y%m%d")
            request_id = str(uuid.uuid4())
            ip = _normalize_client_ip(client_ip)

            logged_messages = _messages_for_log(messages)
            message_preview = _build_message_preview(logged_messages)
            message_count = len(logged_messages)
            total_chars = _count_total_chars(logged_messages)

            common_fields = {
                "request_id": request_id,
                "timestamp": timestamp,
                "client_ip": ip,
                "teacher": teacher_name or "未知",
                "api_key": _mask_api_key(api_key),
                "model": model,
                "is_valid": is_valid,
                "validation_result": validation_result,
            }

            full_entry = {
                **common_fields,
                "messages": logged_messages,
            }
            summary_entry = {
                **common_fields,
                "message_count": message_count,
                "total_chars": total_chars,
                "message_preview": message_preview,
            }

            with open(self._get_full_log_file_path(date_str), "a", encoding="utf-8") as f:
                f.write(json.dumps(full_entry, ensure_ascii=False) + "\n")

            with open(self._get_log_file_path(date_str), "a", encoding="utf-8") as f:
                f.write(json.dumps(summary_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logging.error(f"記錄請求失敗: {e}")

    def get_log_detail(self, request_id: str, date: str | None = None) -> dict[str, Any] | None:
        target_date = date or datetime.now(TZ_UTC8).strftime("%Y%m%d")
        log_file = self._get_full_log_file_path(target_date)
        if not log_file.exists():
            return None

        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if item.get("request_id") == request_id:
                        return item
        except Exception as e:
            logging.error(f"讀取完整請求記錄失敗: {e}")
            return None

        return None

    def query_logs(
        self,
        date: str | None = None,
        teacher: str | None = None,
        model: str | None = None,
        is_valid: bool | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        target_date = date or datetime.now(TZ_UTC8).strftime("%Y%m%d")
        log_file = self._get_log_file_path(target_date)
        if not log_file.exists():
            return {"items": [], "total": 0, "has_more": False}

        teacher_filter = teacher.strip() if teacher else None
        model_filter = model.strip() if model else None
        keyword_filter = keyword.strip().lower() if keyword else None

        matched: list[dict[str, Any]] = []
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if teacher_filter and item.get("teacher") != teacher_filter:
                        continue
                    if model_filter and item.get("model") != model_filter:
                        continue
                    if is_valid is not None and bool(item.get("is_valid")) is not is_valid:
                        continue
                    if keyword_filter and keyword_filter not in _item_search_text(item):
                        continue

                    matched.append(item)
        except Exception as e:
            logging.error(f"讀取請求記錄失敗: {e}")
            return {"items": [], "total": 0, "has_more": False}

        matched.reverse()
        total = len(matched)
        start = max(offset, 0)
        end = start + max(limit, 1)
        items = matched[start:end]
        return {"items": items, "total": total, "has_more": end < total}
