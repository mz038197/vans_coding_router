from __future__ import annotations

PICKED_MODELS = "picked"
AUTOMATIC_MODELS = "automatic"
CLASSROOM_MODEL_CHOICE_UNCHANGED = object()


def normalize_classroom_model_choice(value: object) -> str:
    if value == PICKED_MODELS or value == AUTOMATIC_MODELS:
        return value
    raise ValueError("模型選擇只能是學生自選或自動")


def _vcr_auto() -> str:
    from src.domain.vcr_auto import VCR_AUTO_MODEL_ID

    return VCR_AUTO_MODEL_ID


def choice_accepts_model(choice: str | None, model_id: object, shelf_ids: list[str]) -> bool:
    auto = _vcr_auto()
    if choice == AUTOMATIC_MODELS:
        return model_id == auto
    if choice == PICKED_MODELS:
        return isinstance(model_id, str) and model_id in shelf_ids
    return model_id == auto or (isinstance(model_id, str) and model_id in shelf_ids)


def student_list_ids(choice: str | None, shelf_ids: list[str]) -> list[str]:
    if choice == PICKED_MODELS:
        return list(shelf_ids)
    return [_vcr_auto()]
