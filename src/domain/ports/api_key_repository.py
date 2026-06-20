from typing import Any, Protocol


class ApiKeyRepositoryPort(Protocol):
    def verify_api_key(self, api_key: str) -> tuple[bool, str | None]:
        ...

    def is_enabled(self) -> bool:
        ...

    def get_all_config(self) -> dict[str, Any]:
        ...

    def add_teacher(self, teacher_name: str) -> None:
        ...

    def delete_teacher(self, teacher_name: str) -> bool:
        ...

    def add_api_key(self, teacher_name: str, name: str, key: str, enabled: bool = True) -> None:
        ...

    def update_api_key(
        self,
        teacher_name: str,
        old_key: str,
        name: str,
        key: str,
        enabled: bool,
    ) -> bool:
        ...

    def update_api_key_status(self, teacher_name: str, key: str, enabled: bool) -> bool:
        ...

    def delete_api_key(self, teacher_name: str, key: str) -> bool:
        ...
