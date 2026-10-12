"""Web Search follows the Class Session's switch, not a shelf."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fakes import FakeLLMGateway, FakeRequestLogger, FakeWebSearch
from src.application.use_cases.api_use_case import ApiUseCase
from src.application.use_cases.auth_use_case import AuthUseCase
from src.application.use_cases.portal_use_case import PortalUseCase
from src.application.web_search_rate_limit import WebSearchRateLimiter
from src.domain.errors import UpstreamServiceError
from src.infrastructure.config import AuthSettings, DatabaseSettings, RouterSettings
from src.infrastructure.repositories.sqlite_router_repository import SqliteRouterRepository
from src.presentation.fastapi.error_handlers import register_error_handlers
from src.presentation.fastapi.middleware.api_key_middleware import ApiKeyMiddleware
from src.presentation.fastapi.routers.api_router import create_api_router
from src.presentation.fastapi.routers.portal_router import create_portal_router

NO_SEARCH_KEY = object()
QUERY = {"queries": ["台中 活動"]}


def _settings(tmp_path) -> RouterSettings:
    return RouterSettings(
        path=str(tmp_path / "router.yaml"),
        public_url="http://testserver",
        database=DatabaseSettings(path=str(tmp_path / "router.db"), archive_dir=str(tmp_path / "archive")),
        auth=AuthSettings(teacher_domain="school.edu", session_secret="test-secret"),
    )


class FakeClock:
    """Seconds that pass only when a test says so."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _app_client(tmp_path, web_search=None, clock=None):
    """The API and the Portal on one app, with the search backend swapped for a fake."""
    settings = _settings(tmp_path)
    repo = SqliteRouterRepository(settings.database.path, settings)
    search = None if web_search is NO_SEARCH_KEY else (web_search or FakeWebSearch())
    api_use_case = ApiUseCase(
        gateway=FakeLLMGateway(),
        api_key_repo=repo,
        logger=FakeRequestLogger(),
        web_search=search,
        web_search_limiter=WebSearchRateLimiter(clock=clock or FakeClock()),
    )
    app = FastAPI()
    register_error_handlers(app)
    app.add_middleware(ApiKeyMiddleware, auth_use_case=AuthUseCase(api_key_repo=repo))
    app.include_router(create_api_router(api_use_case))
    app.include_router(create_portal_router(PortalUseCase(repo, settings), settings))
    client = TestClient(app, base_url="http://127.0.0.1", headers={"Origin": "http://testserver"})
    return client, repo, search


def _teacher(repo):
    return repo.upsert_google_user("teacher@school.edu", "Teacher")


def _personal_headers(repo):
    return {"Authorization": f"Bearer {repo.issue_long_lived_key(_teacher(repo)['id'])}"}


def _sitting(client, repo):
    """A teacher opens a sitting through the Portal and a student redeems its invite."""
    teacher = _teacher(repo)
    token, _ = repo.create_portal_session(teacher["id"], "Test browser")
    cookies = {"vcr_portal_session": token}
    klass = repo.create_class(teacher["id"], "AI 素養", None, 2)
    created = client.post(
        f"/teacher/classes/{klass['id']}/sessions",
        cookies=cookies,
        json={"name": "第一堂", "ttl_hours": 2},
    )
    assert created.status_code == 200
    session = created.json()
    student = repo.upsert_google_user("student@gmail.com", "Student")
    redeem = repo.redeem_invite(session["invite_code"], student["id"])
    headers = {"Authorization": f"Bearer {redeem['api_key']}"}
    return teacher, klass, session, cookies, headers


def _set_web_search(client, klass, session, cookies, enabled: bool):
    response = client.patch(
        f"/teacher/classes/{klass['id']}/sessions/{session['id']}",
        cookies=cookies,
        json={"web_search_enabled": enabled},
    )
    assert response.status_code == 200
    return response.json()


def test_personal_api_key_search_returns_titles_links_and_excerpts(tmp_path):
    client, repo, search = _app_client(tmp_path)

    response = client.post(
        "/v1/search",
        headers=_personal_headers(repo),
        json={"queries": ["台中 活動", "今天 股市"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "results": [
            {
                "query": "台中 活動",
                "title": "台中 活動 的結果",
                "url": "https://example.com/page",
                "text": "關於 台中 活動 的內文片段",
            },
            {
                "query": "今天 股市",
                "title": "今天 股市 的結果",
                "url": "https://example.com/page",
                "text": "關於 今天 股市 的內文片段",
            },
        ]
    }
    assert search.calls == [["台中 活動", "今天 股市"]]


def test_classroom_api_key_search_follows_the_sitting_switch(tmp_path):
    client, repo, search = _app_client(tmp_path)
    _teacher_row, klass, session, cookies, headers = _sitting(client, repo)
    assert not session["web_search_enabled"]

    blocked = client.post("/v1/search", headers=headers, json=QUERY)
    assert blocked.status_code == 403
    assert blocked.json() == {
        "error": {
            "message": "此課堂未開放網路搜尋",
            "type": "invalid_request_error",
            "param": None,
            "code": "web_search_disabled",
        }
    }
    assert search.calls == []

    assert _set_web_search(client, klass, session, cookies, True)["web_search_enabled"]
    opened = client.post("/v1/search", headers=headers, json=QUERY)
    assert opened.status_code == 200
    assert opened.json()["results"][0]["url"] == "https://example.com/page"

    assert not _set_web_search(client, klass, session, cookies, False)["web_search_enabled"]
    closed = client.post("/v1/search", headers=headers, json=QUERY)
    assert closed.status_code == 403
    assert closed.json()["error"]["code"] == "web_search_disabled"
    assert search.calls == [["台中 活動"]]


def test_a_sitting_from_before_web_search_stays_closed(tmp_path):
    client, repo, _search = _app_client(tmp_path)
    _teacher_row, klass, session, cookies, headers = _sitting(client, repo)
    with repo._connect() as conn:
        conn.execute("ALTER TABLE class_sessions DROP COLUMN web_search_enabled")

    client, repo, search = _app_client(tmp_path)

    blocked = client.post("/v1/search", headers=headers, json=QUERY)
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "web_search_disabled"
    assert search.calls == []
    _set_web_search(client, klass, session, cookies, True)
    assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer vcr_sk_not-a-key"}])
def test_search_without_a_valid_key_is_refused(tmp_path, headers):
    client, _repo, search = _app_client(tmp_path)

    response = client.post("/v1/search", headers=headers, json=QUERY)

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert response.json()["error"]["code"] == "invalid_api_key"
    assert search.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"queries": []},
        {"queries": ["a", "b", "c", "d"]},
        {"queries": ["x" * 1001]},
        {"queries": ["ok", "   "]},
        {"queries": [42]},
        {"queries": "台中 活動"},
        ["台中 活動"],
    ],
)
def test_search_refuses_a_bad_query_list(tmp_path, body):
    client, repo, search = _app_client(tmp_path)

    response = client.post("/v1/search", headers=_personal_headers(repo), json=body)

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    assert response.json()["error"]["param"] == "queries"
    assert search.calls == []


def test_search_accepts_three_queries_of_a_thousand_characters(tmp_path):
    client, repo, search = _app_client(tmp_path)
    queries = ["x" * 1000, "y" * 1000, "z" * 1000]

    response = client.post("/v1/search", headers=_personal_headers(repo), json={"queries": queries})

    assert response.status_code == 200
    assert search.calls == [queries]


def test_search_is_unavailable_when_no_search_key_is_configured(tmp_path):
    client, repo, _search = _app_client(tmp_path, web_search=NO_SEARCH_KEY)

    response = client.post("/v1/search", headers=_personal_headers(repo), json=QUERY)

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "server_error"
    assert response.json()["error"]["code"] == "web_search_unavailable"


def test_search_backend_failure_uses_the_upstream_failure_shape(tmp_path):
    search = FakeWebSearch()
    client, repo, _search = _app_client(tmp_path, web_search=search)
    headers = _personal_headers(repo)

    search.error = UpstreamServiceError(
        status_code=500,
        backend="tavily",
        body={"error": "search backend exploded"},
    )
    failed = client.post("/v1/search", headers=headers, json=QUERY)
    assert failed.status_code == 500
    assert failed.json() == {
        "error": {
            "message": "search backend exploded",
            "type": "server_error",
            "param": None,
            "code": None,
        }
    }

    search.error = UpstreamServiceError(status_code=401, backend="tavily", body={"error": "bad key"})
    refused = client.post("/v1/search", headers=headers, json=QUERY)
    assert refused.status_code == 502
    assert refused.json()["error"]["code"] == "upstream_authentication_error"
    assert "bad key" not in refused.text


def test_a_search_writes_no_prompt_log(tmp_path):
    client, repo, _search = _app_client(tmp_path)
    teacher, klass, session, cookies, headers = _sitting(client, repo)
    _set_web_search(client, klass, session, cookies, True)
    assert repo.is_prompt_logging_enabled(session["id"]) is True

    assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200

    assert repo.list_prompt_logs(teacher["id"], klass["id"]) == []


def test_the_eleventh_search_in_a_minute_is_rate_limited(tmp_path):
    client, repo, search = _app_client(tmp_path)
    headers = _personal_headers(repo)

    for _ in range(10):
        assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200
    limited = client.post("/v1/search", headers=headers, json=QUERY)

    assert limited.status_code == 429
    assert limited.json() == {
        "error": {
            "message": "搜尋太頻繁，請稍後再試",
            "type": "rate_limit_error",
            "param": None,
            "code": "web_search_rate_limited",
        }
    }
    assert len(search.calls) == 10


def test_a_key_may_search_again_once_a_minute_has_passed(tmp_path):
    clock = FakeClock()
    client, repo, search = _app_client(tmp_path, clock=clock)
    headers = _personal_headers(repo)

    for _ in range(10):
        assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200
    clock.advance(59)
    assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 429

    clock.advance(1)
    assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200
    assert len(search.calls) == 11


def test_each_key_has_its_own_count(tmp_path):
    client, repo, _search = _app_client(tmp_path)
    first = _personal_headers(repo)
    other = repo.upsert_google_user("other@school.edu", "Other")
    second = {"Authorization": f"Bearer {repo.issue_long_lived_key(other['id'])}"}

    for _ in range(10):
        assert client.post("/v1/search", headers=first, json=QUERY).status_code == 200
    assert client.post("/v1/search", headers=first, json=QUERY).status_code == 429

    assert client.post("/v1/search", headers=second, json=QUERY).status_code == 200


def test_a_classroom_api_key_has_the_same_limit(tmp_path):
    client, repo, search = _app_client(tmp_path)
    _teacher_row, klass, session, cookies, headers = _sitting(client, repo)
    _set_web_search(client, klass, session, cookies, True)

    for _ in range(10):
        assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200
    limited = client.post("/v1/search", headers=headers, json=QUERY)

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "web_search_rate_limited"
    assert len(search.calls) == 10


def test_searches_refused_by_the_switch_do_not_count(tmp_path):
    client, repo, search = _app_client(tmp_path)
    _teacher_row, klass, session, cookies, headers = _sitting(client, repo)

    for _ in range(11):
        blocked = client.post("/v1/search", headers=headers, json=QUERY)
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "web_search_disabled"
    assert search.calls == []

    _set_web_search(client, klass, session, cookies, True)
    assert client.post("/v1/search", headers=headers, json=QUERY).status_code == 200
