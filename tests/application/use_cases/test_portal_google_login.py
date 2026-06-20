from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.application.use_cases.portal_use_case import PortalUseCase


def _portal(tmp_path, *, open_registration: bool = True):
    settings = RouterSettings(
        path=str(tmp_path / "router.yaml"),
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(open_registration=open_registration),
    )
    repo = SqliteRouterRepository(settings.database.path, settings)
    return PortalUseCase(repo, settings), repo


def test_google_login_blocks_new_user_when_registration_closed(tmp_path):
    portal, _ = _portal(tmp_path, open_registration=False)
    try:
        portal.google_login("new@gmail.com", "New")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert str(exc) == "尚未開放註冊"


def test_google_login_allows_existing_user_when_registration_closed(tmp_path):
    portal, repo = _portal(tmp_path, open_registration=False)
    existing = repo.upsert_google_user("old@gmail.com", "Old")
    user = portal.google_login("old@gmail.com", "Old Updated", "sub-1")
    assert user["id"] == existing["id"]
    assert user["name"] == "Old Updated"
