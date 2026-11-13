from dataclasses import dataclass, field
from typing import Any

from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.per_minute_rate_limit import PerMinuteRateLimiter
from src.application.use_cases.key_check_use_case import KeyCheckUseCase
from src.application.use_cases.lobby_use_case import LobbyHostUseCase
from src.application.use_cases.oauth_use_case import OAuthUseCase
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
    prompt_log_archive_after_days: int = 15
    prompt_log_delete_after_days: int = 30
    router_settings: Any | None = None
    key_check_use_case: KeyCheckUseCase | None = None
    # SHA-256 hex of each Partner Service's Service Credential -> service name (ADR 0076).
    service_tokens: dict[str, str] = field(default_factory=dict)
    key_check_rate_limiter: PerMinuteRateLimiter | None = None
    # The OAuth authorization server (ADR 0094); None when no signing key is configured.
    oauth_use_case: OAuthUseCase | None = None
