"""Course Catalog YAML shape shared with classroom-one-click-install."""

from __future__ import annotations

from typing import Any

import yaml

ACTION_KINDS = frozenset({"skill", "package", "mcp"})
DEFAULT_COURSE_CATALOG_YAML = "actions: []\n"


class _CatalogDumper(yaml.SafeDumper):
    """Dumper that emits multiline strings as literal block scalars."""


def _looks_like_yaml_nonstring(data: str) -> bool:
    stripped = data.strip()
    if stripped != data or stripped == "":
        return True
    lowered = stripped.lower()
    if lowered in {"true", "false", "null", "yes", "no", "on", "off", "~"}:
        return True
    if stripped[:1] in "-?:" and len(stripped) > 1:
        return True
    try:
        float(stripped)
        return True
    except ValueError:
        return False


def _literal_str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    style = '"' if _looks_like_yaml_nonstring(data) else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_CatalogDumper.add_representer(str, _literal_str_representer)


def _as_text(value: object) -> object:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return value


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
        id_value = _as_text(row.get("id"))
        title = _as_text(row.get("title"))
        command = _as_text(row.get("command"))
        kind = _as_text(row.get("kind"))
        description = _as_text(row.get("description")) if row.get("description") is not None else None

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

    snippets = _parse_snippets(doc.get("snippets"))
    dumped: dict[str, Any] = {"actions": actions}
    if snippets:
        dumped["snippets"] = snippets
    return yaml.dump(dumped, Dumper=_CatalogDumper, allow_unicode=True, sort_keys=False)


def _parse_snippets(snippets_raw: object) -> list[dict[str, Any]]:
    if snippets_raw is None:
        return []
    if not isinstance(snippets_raw, list):
        raise ValueError("頂層鍵 snippets 若提供須為陣列")

    snippets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, row in enumerate(snippets_raw):
        if not isinstance(row, dict):
            raise ValueError(f"snippets[{i}] 必須是物件")
        id_value = _as_text(row.get("id"))
        title = _as_text(row.get("title"))
        body = row.get("body")
        paste_hint = _as_text(row.get("paste_hint")) if row.get("paste_hint") is not None else None

        if not _non_empty_str(id_value) or not _non_empty_str(title):
            raise ValueError(f"snippets[{i}] 缺少必填欄位 id／title／body")
        if not isinstance(body, str) or len(body) == 0:
            raise ValueError(f"snippets[{i}] 缺少必填欄位 id／title／body")

        snippet_id = id_value.strip()
        if snippet_id in seen_ids:
            raise ValueError(f"snippets 內 id 重複：{snippet_id}")
        seen_ids.add(snippet_id)

        snippet: dict[str, Any] = {
            "id": snippet_id,
            "title": title.strip(),
            "body": body,
        }
        if paste_hint is not None:
            if not _non_empty_str(paste_hint):
                raise ValueError(f"snippets[{i}].paste_hint 若提供須為非空字串")
            snippet["paste_hint"] = paste_hint.strip()
        snippets.append(snippet)
    return snippets


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
