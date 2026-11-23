import pytest

from src.bootstrap import build_container


def test_public_deployment_fails_startup_without_complete_google_oauth(tmp_path, monkeypatch):
    config = tmp_path / "router.yaml"
    config.write_text(
        "\n".join(
            [
                'public_url: "https://router.example"',
                "auth:",
                '  google_client_id: ""',
                '  google_client_secret: ""',
                "database:",
                f'  path: "{(tmp_path / "router.db").as_posix()}"',
                f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)

    with pytest.raises(ValueError, match="Google OAuth"):
        build_container(request_timeout=1.0, config_path=str(config))


def _config(tmp_path, monkeypatch, public_url, session_secret):
    config = tmp_path / "router.yaml"
    config.write_text(
        "\n".join(
            [
                f'public_url: "{public_url}"',
                "auth:",
                '  google_client_id: "cid"',
                '  google_client_secret: "csecret"',
                "database:",
                f'  path: "{(tmp_path / "router.db").as_posix()}"',
                f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    if session_secret is None:
        monkeypatch.delenv("SESSION_SECRET", raising=False)
    else:
        monkeypatch.setenv("SESSION_SECRET", session_secret)
    return str(config)


@pytest.mark.parametrize(
    "session_secret",
    [None, "dev-session-secret", "change-me", "change-me-stg", "x" * 31, " " * 40],
    ids=["unset", "code-default", "example", "staging-example", "31-characters", "blank"],
)
def test_public_deployment_refuses_a_weak_session_secret(tmp_path, monkeypatch, session_secret):
    config = _config(tmp_path, monkeypatch, "https://router.example", session_secret)

    with pytest.raises(ValueError, match="SESSION_SECRET"):
        build_container(request_timeout=1.0, config_path=config)


def test_fly_deployment_with_a_loopback_url_refuses_a_weak_session_secret(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch, "http://127.0.0.1:8080", None)
    monkeypatch.setenv("FLY_APP_NAME", "vans-coding-router")

    with pytest.raises(ValueError, match="SESSION_SECRET"):
        build_container(request_timeout=1.0, config_path=config)


def test_public_deployment_starts_with_a_32_character_session_secret(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch, "https://router.example", "x" * 32)

    build_container(request_timeout=1.0, config_path=config)


def test_local_development_starts_without_a_session_secret(tmp_path, monkeypatch):
    config = _config(tmp_path, monkeypatch, "http://127.0.0.1:8000", None)

    build_container(request_timeout=1.0, config_path=config)
