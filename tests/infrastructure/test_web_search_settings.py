from pathlib import Path

import pytest

from src.bootstrap import build_container
from src.infrastructure.config import (
    apply_runtime_settings,
    load_router_settings,
    resolve_web_search_api_key,
)
from src.infrastructure.search.tavily_web_search import TavilyWebSearch

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _config(tmp_path: Path, *extra_lines: str) -> str:
    config = tmp_path / "router.yaml"
    config.write_text(
        "\n".join(
            [
                "database:",
                f'  path: "{(tmp_path / "router.db").as_posix()}"',
                f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
                *extra_lines,
            ]
        ),
        encoding="utf-8",
    )
    return str(config)


def test_the_config_names_the_env_var_that_holds_the_search_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_SEARCH_KEY", "tvly-secret")
    settings = load_router_settings(_config(tmp_path, "web_search:", '  api_key_env: "MY_SEARCH_KEY"'))

    assert resolve_web_search_api_key(settings.web_search) == "tvly-secret"
    overridden = apply_runtime_settings(settings, {"student_default_ttl_hours": "3"})
    assert resolve_web_search_api_key(overridden.web_search) == "tvly-secret"

    monkeypatch.delenv("MY_SEARCH_KEY")
    assert resolve_web_search_api_key(settings.web_search) == ""


def test_a_config_without_a_search_key_has_none(tmp_path):
    settings = load_router_settings(_config(tmp_path))

    assert resolve_web_search_api_key(settings.web_search) == ""


@pytest.mark.parametrize("name", ["router.example.yaml", "router.prod.yaml", "router.stg.example.yaml"])
def test_shipped_configs_name_the_tavily_key(name, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-shipped")
    settings = load_router_settings(str(CONFIG_DIR / name))

    assert resolve_web_search_api_key(settings.web_search) == "tvly-shipped"


def test_startup_searches_with_tavily_only_when_the_key_is_set(tmp_path, monkeypatch):
    config = _config(tmp_path, "web_search:", '  api_key_env: "MY_SEARCH_KEY"')

    monkeypatch.delenv("MY_SEARCH_KEY", raising=False)
    without_key = build_container(request_timeout=1.0, config_path=config)
    assert without_key.api_use_case.web_search_backend is None

    monkeypatch.setenv("MY_SEARCH_KEY", "tvly-secret")
    with_key = build_container(request_timeout=1.0, config_path=config)
    assert isinstance(with_key.api_use_case.web_search_backend, TavilyWebSearch)
