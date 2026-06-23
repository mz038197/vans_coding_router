from __future__ import annotations

import re

_MENTION_RE = re.compile(r"@([\w\u4e00-\u9fff][\w\u4e00-\u9fff\s-]*)")


def normalize_display_name(name: str) -> str:
    return name.strip().casefold()


def parse_mentions(
    text: str,
    *,
    display_name_to_agent_id: dict[str, str],
) -> list[str]:
    if not text or not display_name_to_agent_id:
        return []

    sorted_names = sorted(display_name_to_agent_id.keys(), key=len, reverse=True)
    norm_map = {normalize_display_name(n): n for n in sorted_names}

    seen: set[str] = set()
    result: list[str] = []

    for match in _MENTION_RE.finditer(text):
        raw = match.group(1).strip()
        if not raw:
            continue
        agent_id = _resolve_mention(raw, sorted_names, norm_map, display_name_to_agent_id)
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            result.append(agent_id)

    return result


def _resolve_mention(
    raw: str,
    sorted_names: list[str],
    norm_map: dict[str, str],
    display_name_to_agent_id: dict[str, str],
) -> str | None:
    raw_norm = normalize_display_name(raw)
    if raw_norm in norm_map:
        canonical = norm_map[raw_norm]
        return display_name_to_agent_id.get(canonical)

    for name in sorted_names:
        if raw_norm == normalize_display_name(name):
            return display_name_to_agent_id[name]

    for name in sorted_names:
        name_norm = normalize_display_name(name)
        if name_norm.startswith(raw_norm):
            return display_name_to_agent_id[name]

    for name in sorted_names:
        name_norm = normalize_display_name(name)
        if raw_norm.startswith(name_norm):
            return display_name_to_agent_id[name]

    for name in sorted_names:
        if raw == display_name_to_agent_id.get(name):
            return raw
    if raw in display_name_to_agent_id.values():
        return raw
    return None
