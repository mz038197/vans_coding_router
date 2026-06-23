from dataclasses import dataclass
from typing import Any

from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.lobby_use_case import LobbyHostUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.domain.ports.llm_gateway import LLMGatewayPort
from src.infrastructure.logging.file_request_logger import FileRequestLogger
from src.domain.ports.api_key_repository import ApiKeyRepositoryPort


@dataclass
class AppContainer:
    api_key_repo: ApiKeyRepositoryPort
    request_logger: FileRequestLogger
    llm_gateway: LLMGatewayPort
    auth_use_case: AuthUseCase
    api_use_case: ApiUseCase
    portal_use_case: PortalUseCase | None = None
    lobby_use_case: LobbyHostUseCase | None = None
    archive_repo: Any | None = None
    prompt_log_retention_days: int = 30
    router_settings: Any | None = None
