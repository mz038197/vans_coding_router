from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router


def build_test_client(fake_repo, fake_gateway, fake_logger) -> TestClient:
    auth_use_case = AuthUseCase(api_key_repo=fake_repo)
    api_use_case = ApiUseCase(gateway=fake_gateway, api_key_repo=fake_repo, logger=fake_logger)

    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=auth_use_case)
    app.include_router(create_api_router(api_use_case))
    return TestClient(app)
