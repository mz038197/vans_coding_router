"""Patch local VS Code chatLanguageModels.json for VSRouter Agent compatibility."""
from __future__ import annotations

import json
from pathlib import Path

from src.infrastructure.vscode.merge_chat_language_models import load_vans_template
from src.infrastructure.vscode.model_defaults import patch_model_from_template

TEMPLATE_BY_ID = {m["id"]: m for m in load_vans_template()[0]["models"] if m.get("id")}
PATHS = [
    Path.home() / "AppData/Roaming/Code/User/chatLanguageModels.json",
    Path.home() / "AppData/Roaming/Code - Insiders/User/chatLanguageModels.json",
]


def fix_file(path: Path) -> None:
    if not path.exists():
        print(f"skip missing {path}")
        return
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    changed = False
    for provider in data:
        if provider.get("vendor") != "customendpoint" or provider.get("name") != "VSRouter":
            continue
        for model in provider.get("models", []):
            if not isinstance(model, dict):
                continue
            before = json.dumps(model, sort_keys=True)
            template = TEMPLATE_BY_ID.get(model.get("id", ""))
            if template:
                patch_model_from_template(model, template)
            if model.get("url", "").endswith("/v1/responses"):
                model["url"] = "https://ai.vanscoding.com/v1"
            if "requestHeaders" not in model:
                model["requestHeaders"] = {"Authorization": "Bearer ${apiKey}"}
            model.setdefault("thinking", True)
            model.setdefault("reasoningEffortFormat", "responses")
            if json.dumps(model, sort_keys=True) != before:
                changed = True
    if not changed:
        print(f"no change {path}")
        return
    backup = path.with_suffix(path.suffix + ".bak-fix")
    backup.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"fixed {path}")


if __name__ == "__main__":
    for item in PATHS:
        fix_file(item)
