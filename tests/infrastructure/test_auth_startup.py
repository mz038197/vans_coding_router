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
