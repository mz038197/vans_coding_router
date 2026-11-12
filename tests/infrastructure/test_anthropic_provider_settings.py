from pathlib import Path

import pytest

from src.bootstrap import build_container
from src.infrastructure.config import load_router_settings
from src.infrastructure.gateways.anthropic_gateway import AnthropicGateway

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _config(tmp_path: Path) -> str:
    config = tmp_path / "router.yaml"
    config.write_text(
        "\n".join(
            [
                "database:",
                f'  path: "{(tmp_path / "router.db").as_posix()}"',
                f'  archive_dir: "{(tmp_path / "archive").as_posix()}"',
                "providers:",
                "  anthropic:",
                "    type: anthropic",
                '    base_url: "https://api.anthropic.com/v1"',
                "    api_key_envs: [ANTHROPIC_API_KEY, ANTHROPIC_API_KEY_2]",
                "    max_concurrent_per_key: 10",
            ]
        ),
        encoding="utf-8",
    )
    return str(config)


def test_an_anthropic_provider_builds_an_anthropic_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key-a")

    container = build_container(request_timeout=1.0, config_path=_config(tmp_path))

    assert isinstance(container.llm_gateway.gateways["anthropic"], AnthropicGateway)


@pytest.mark.parametrize("name", ["router.example.yaml", "router.prod.yaml", "router.stg.example.yaml"])
def test_shipped_configs_list_the_anthropic_provider(name):
    provider = load_router_settings(str(CONFIG_DIR / name)).providers["anthropic"]

    assert provider.type == "anthropic"
    assert provider.base_url == "https://api.anthropic.com/v1"
    assert provider.api_key_envs == ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_2")
    assert provider.max_concurrent_per_key == 10
    assert provider.enabled
