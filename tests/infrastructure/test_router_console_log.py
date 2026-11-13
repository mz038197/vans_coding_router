"""Router logs under src reach the process output (Fly logs), even with vans-signals forwarding on."""

import asyncio
import logging
from types import SimpleNamespace

from app import application_lifespan


class _Gateway:
    async def startup(self):
        return None

    async def shutdown(self):
        return None


def _run_lifespan(portal) -> None:
    container = SimpleNamespace(archive_repo=None, llm_gateway=_Gateway(), portal_use_case=portal)

    async def scenario():
        async with application_lifespan(container):
            logging.getLogger("src.infrastructure.gateways.anthropic_gateway").warning(
                "anthropic_input_transformation reason=prefix_binding_mismatch"
            )
            logging.getLogger("src.infrastructure.gateways.openai_compatible_gateway").info(
                "key_failover provider=openrouter failed_index=0"
            )

    asyncio.run(scenario())


def test_router_logs_reach_the_console_while_signals_forwarding_is_on(monkeypatch, capsys):
    # Production sets VANS_SIGNALS_*; its handler on `src` used to silence Python's fallback output.
    monkeypatch.setenv("VANS_SIGNALS_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("VANS_SIGNALS_TOKEN", "router-token")

    class Portal:
        async def fill_upstream_model_catalog(self):
            logging.getLogger("src.application.upstream_model_catalog").error(
                "Upstream Model Catalog round did not update: anthropic\nanthropic: HTTP 400"
            )

    _run_lifespan(Portal())

    err = capsys.readouterr().err
    assert "Upstream Model Catalog round did not update: anthropic" in err
    assert "anthropic: HTTP 400" in err
    assert "anthropic_input_transformation reason=prefix_binding_mismatch" in err
    assert "key_failover provider=openrouter failed_index=0" in err
    assert "ERROR" in err and "WARNING" in err and "INFO" in err
    assert "src.application.upstream_model_catalog" in err


def test_each_log_is_printed_once_across_restarts(monkeypatch, capsys):
    monkeypatch.delenv("VANS_SIGNALS_URL", raising=False)

    class Portal:
        async def fill_upstream_model_catalog(self):
            return None

    _run_lifespan(Portal())
    _run_lifespan(Portal())
    capsys.readouterr()

    async def scenario():
        container = SimpleNamespace(archive_repo=None, llm_gateway=_Gateway(), portal_use_case=Portal())
        async with application_lifespan(container):
            logging.getLogger("src.x").warning("printed once")

    asyncio.run(scenario())
    assert capsys.readouterr().err.count("printed once") == 1
