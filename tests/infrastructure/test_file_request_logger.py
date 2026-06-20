import json
from pathlib import Path

from src.infrastructure.logging.file_request_logger import (
    PREVIEW_MAX_LEN,
    PREVIEW_TRUNCATED_SUFFIX,
    FileRequestLogger,
    _build_message_preview,
)


def test_summary_log_excludes_messages(tmp_path: Path):
    logger = FileRequestLogger(log_dir=tmp_path)
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "hello student"},
    ]

    logger.log_validation_result(
        teacher_name="TeacherA",
        api_key="valid-key",
        model="gemma4:26b",
        messages=messages,
        is_valid=True,
        client_ip="203.71.78.5",
    )

    summary = json.loads(next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8").strip())
    assert "messages" not in summary
    assert summary["message_preview"] == "hello student"
    assert summary["client_ip"] == "203.71.78.5"
    assert summary["message_count"] == 2
    assert summary["request_id"]


def test_full_log_stores_complete_messages(tmp_path: Path):
    logger = FileRequestLogger(log_dir=tmp_path)
    long_content = "user-question-" + ("x" * 800)
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": long_content},
    ]

    logger.log_validation_result(
        teacher_name="TeacherA",
        api_key="valid-key",
        model="gemma4:26b",
        messages=messages,
        is_valid=True,
    )

    full = json.loads(next((tmp_path / "full").glob("log_*.log")).read_text(encoding="utf-8").strip())
    assert len(full["messages"]) == 2
    assert full["messages"][1]["content"] == long_content


def test_request_id_links_summary_and_full(tmp_path: Path):
    logger = FileRequestLogger(log_dir=tmp_path)
    logger.log_validation_result(
        teacher_name="TeacherA",
        api_key="valid-key",
        model="gemma4:26b",
        messages=[{"role": "user", "content": "linked"}],
        is_valid=True,
    )

    summary = json.loads(next(tmp_path.glob("log_*.log")).read_text(encoding="utf-8").strip())
    detail = logger.get_log_detail(summary["request_id"])
    assert detail is not None
    assert detail["request_id"] == summary["request_id"]
    assert detail["messages"][0]["content"] == "linked"


def test_build_message_preview_extracts_user_request():
    wrapped = (
        "<context>\nThe current date is 2026-06-15.\n</context>\n"
        "<reminderInstructions>tool rules</reminderInstructions>\n"
        "<userRequest>幫我新增番茄鐘頁面</userRequest>"
    )
    preview = _build_message_preview([{"role": "user", "content": wrapped}])
    assert preview == "幫我新增番茄鐘頁面"


def test_build_message_preview_prefers_last_user_request():
    messages = [
        {
            "role": "user",
            "content": "<userRequest>建立 Pomodoro 頁</userRequest>",
        },
        {
            "role": "user",
            "content": (
                "<context>noise</context>"
                "<userRequest>調整計時器顏色</userRequest>"
            ),
        },
    ]
    preview = _build_message_preview(messages)
    assert preview == "調整計時器顏色"


def test_build_message_preview_extracts_user_query_for_cursor():
    wrapped = (
        "<context>noise</context>\n"
        "<user_query>學生真正的問題</user_query>\n"
        "<reminderInstructions>more noise</reminderInstructions>"
    )
    preview = _build_message_preview([{"role": "user", "content": wrapped}])
    assert preview == "學生真正的問題"


def test_build_message_preview_without_tags_uses_raw_user_text():
    preview = _build_message_preview([{"role": "user", "content": "hello from langchain"}])
    assert preview == "hello from langchain"


def test_build_message_preview_truncates_long_text():
    long_text = "a" * (PREVIEW_MAX_LEN + 100)
    preview = _build_message_preview([{"role": "user", "content": long_text}])
    assert preview.endswith(PREVIEW_TRUNCATED_SUFFIX)
    assert len(preview) < len(long_text)


def test_get_log_detail_returns_none_for_missing_id(tmp_path: Path):
    logger = FileRequestLogger(log_dir=tmp_path)
    assert logger.get_log_detail("missing-id") is None
