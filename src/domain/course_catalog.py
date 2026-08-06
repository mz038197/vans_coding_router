"""Course Catalog YAML shape shared with classroom-one-click-install."""

from __future__ import annotations

from typing import Any

import yaml

ACTION_KINDS = frozenset({"skill", "package", "mcp"})
DEFAULT_COURSE_CATALOG_YAML = "actions: []\n"


def normalize_course_catalog_yaml(source: str) -> str:
    """Parse, validate, and re-dump catalog YAML. Raises ValueError on failure."""
    if not isinstance(source, str):
        raise ValueError("Course Catalog 必須是字串")
    try:
        doc = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 無法解析：{exc}") from exc

    if not isinstance(doc, dict):
        raise ValueError("根層必須是物件，且含 actions 陣列")

    actions_raw = doc.get("actions")
    if not isinstance(actions_raw, list):
        raise ValueError("缺少頂層鍵 actions（陣列）")

    actions: list[dict[str, Any]] = []
    for i, row in enumerate(actions_raw):
        if not isinstance(row, dict):
            raise ValueError(f"actions[{i}] 必須是物件")
        id_value = row.get("id")
        title = row.get("title")
        command = row.get("command")
        kind = row.get("kind")
        description = row.get("description")

        if not _non_empty_str(id_value) or not _non_empty_str(title) or not _non_empty_str(command):
            raise ValueError(f"actions[{i}] 缺少必填欄位 id／title／command")
        if not _non_empty_str(kind) or kind.strip() not in ACTION_KINDS:
            raise ValueError(f"actions[{i}].kind 必須是 skill／package／mcp")

        action: dict[str, Any] = {
            "id": id_value.strip(),
            "title": title.strip(),
            "kind": kind.strip(),
            "command": command.strip(),
        }
        if description is not None:
            if not _non_empty_str(description):
                raise ValueError(f"actions[{i}].description 若提供須為非空字串")
            action["description"] = description.strip()
        actions.append(action)

    return yaml.safe_dump({"actions": actions}, allow_unicode=True, sort_keys=False)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
