from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.infrastructure.config import load_router_settings
from src.infrastructure.gateways.openai_compatible_gateway import OpenAICompatibleGateway
from src.infrastructure.gateways.routing_gateway import RoutingGateway
from src.infrastructure.logging.file_request_logger import FileRequestLogger
from src.infrastructure.repositories.factory import build_router_repository
from src.presentation.fastapi.dependencies import AppContainer


def build_container(
    request_timeout: float,
    config_path: str | None = None,
) -> AppContainer:
    settings = load_router_settings(config_path)
    api_key_repo = build_router_repository(settings)
    request_logger = FileRequestLogger()
    provider_gateways = {
        name: OpenAICompatibleGateway(provider, timeout=request_timeout)
        for name, provider in settings.providers.items()
        if provider.enabled and provider.type == "openai_compatible" and provider.base_url
    }
    llm_gateway = RoutingGateway(provider_gateways)

    auth_use_case = AuthUseCase(api_key_repo=api_key_repo)
    api_use_case = ApiUseCase(
        gateway=llm_gateway,
        api_key_repo=api_key_repo,
        logger=request_logger,
    )
    portal_use_case = PortalUseCase(api_key_repo, settings)

    return AppContainer(
        api_key_repo=api_key_repo,
        request_logger=request_logger,
        llm_gateway=llm_gateway,
        auth_use_case=auth_use_case,
        api_use_case=api_use_case,
        portal_use_case=portal_use_case,
        archive_repo=api_key_repo,
        prompt_log_retention_days=settings.prompt_logs.retention_days,
        router_settings=settings,
    )
