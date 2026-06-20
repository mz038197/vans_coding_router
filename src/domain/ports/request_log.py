from typing import Any, Protocol


class RequestLogPort(Protocol):
    def log_validation_result(
        self,
        teacher_name: str | None,
        api_key: str,
        model: str,
        messages: list[dict[str, Any]],
        is_valid: bool,
        client_ip: str | None = None,
    ) -> None:
        ...

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
        ...

    def get_log_detail(self, request_id: str, date: str | None = None) -> dict[str, Any] | None:
        ...
