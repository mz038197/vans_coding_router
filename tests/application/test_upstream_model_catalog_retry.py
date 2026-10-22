"""An Upstream Model Catalog fetch that fails transiently is tried again in the same round."""

import asyncio
import logging

from fakes import FakeLLMGateway
from src.application.upstream_model_catalog import UpstreamModelCatalogMemory
from src.domain.errors import UpstreamServiceError
from src.infrastructure.config import ProviderSettings, RouterSettings
from src.infrastructure.gateways.routing_gateway import RoutingGateway

_CATALOG_LOGGER = "src.application.upstream_model_catalog"


class _ScriptedModels:
    """Models calls that raise the scripted failures in order, then answer."""

    def __init__(self, provider: str, *failures: Exception):
        self.provider = provider
        self.failures = list(failures)
        self.calls: list[str | None] = []

    async def __call__(self, *, output_modalities: str | None = None):
        self.calls.append(output_modalities)
        if self.failures:
            raise self.failures.pop(0)
        return {"object": "list", "data": [{"id": f"{self.provider}-model", "name": "M"}]}


def _upstream_error(status_code: int, body="upstream said no") -> UpstreamServiceError:
    return UpstreamServiceError(status_code=status_code, backend="openai", body=body)


def _memory(models: _ScriptedModels, *, models_fn=None, **kwargs) -> UpstreamModelCatalogMemory:
    inner = FakeLLMGateway()
    inner.models = models_fn or models
    provider = models.provider
    gateway = RoutingGateway({provider: inner})
    settings = RouterSettings(
        providers={
            provider: ProviderSettings(
                name=provider,
                enabled=True,
                base_url=f"https://{provider}.test/v1",
            )
        }
    )
    kwargs.setdefault("retry_delays_sec", (0.0, 0.0))
    return UpstreamModelCatalogMemory(lambda: settings, gateway, fetch_timeout_sec=0.2, **kwargs)


def _model_ids(memory: UpstreamModelCatalogMemory, requested: str = "all") -> list[str]:
    return [item["id"] for item in memory.read(requested)["models"]]


def test_a_transient_failure_is_tried_again_and_a_later_success_updates_the_round(caplog):
    models = _ScriptedModels("openai", _upstream_error(503))
    memory = _memory(models)

    with caplog.at_level(logging.WARNING, logger=_CATALOG_LOGGER):
        asyncio.run(memory.fill())

    assert models.calls == [None, None]
    assert _model_ids(memory) == ["openai@openai-model"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_an_auth_failure_is_not_tried_again():
    models = _ScriptedModels("openai", _upstream_error(401))
    memory = _memory(models)

    asyncio.run(memory.fill())

    assert models.calls == [None]
    assert memory.read("all")["unavailable"] is True


def test_a_portion_is_tried_at_most_three_times_in_one_round():
    models = _ScriptedModels(
        "openai",
        _upstream_error(503),
        _upstream_error(429),
        _upstream_error(502),
        _upstream_error(500),
    )
    memory = _memory(models)

    asyncio.run(memory.fill())

    assert models.calls == [None, None, None]
    assert memory.read("all")["unavailable"] is True


def test_each_openrouter_kind_is_tried_again_on_its_own():
    models = _ScriptedModels("openrouter")
    failing_once = {"image"}

    async def scripted(*, output_modalities: str | None = None):
        models.calls.append(output_modalities)
        if output_modalities in failing_once:
            failing_once.discard(output_modalities)
            raise _upstream_error(503)
        return {"object": "list", "data": [{"id": f"{output_modalities}-model", "name": "M"}]}

    memory = _memory(models, models_fn=scripted)

    asyncio.run(memory.fill())

    assert models.calls.count("image") == 2
    assert models.calls.count("text") == 1
    assert _model_ids(memory, "image") == ["openrouter@image-model"]


def test_a_retry_that_would_pass_the_budget_gives_up():
    models = _ScriptedModels("openai", _upstream_error(503))
    memory = _memory(models, retry_delays_sec=(0.5, 0.5), fetch_budget_sec=0.3)

    asyncio.run(memory.fill())

    assert models.calls == [None]
    assert memory.read("all")["unavailable"] is True


def test_a_timed_out_attempt_is_tried_again_within_the_budget():
    models = _ScriptedModels("openai")
    attempts = {"n": 0}

    async def slow_then_fast(*, output_modalities: str | None = None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            await asyncio.sleep(1)
        return {"object": "list", "data": [{"id": "openai-model", "name": "M"}]}

    memory = _memory(models, models_fn=slow_then_fast)

    asyncio.run(memory.fill())

    assert attempts["n"] == 2
    assert _model_ids(memory) == ["openai@openai-model"]


def _errors(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_round_that_still_fails_logs_one_error_with_the_last_status_and_cut_body(caplog):
    long_body = {"error": {"message": "Incorrect API key provided: sk-proj-****abcd" + "x" * 900}}
    models = _ScriptedModels("openai", _upstream_error(503, "busy"), _upstream_error(401, long_body))
    memory = _memory(models)

    with caplog.at_level(logging.WARNING, logger=_CATALOG_LOGGER):
        asyncio.run(memory.fill())

    errors = _errors(caplog)
    assert len(errors) == 1
    header, reason = errors[0].split("\n", 1)
    assert header == "Upstream Model Catalog round did not update: openai"
    assert reason.startswith('openai: HTTP 401: {"error": {"message": "Incorrect API key provided')
    assert len(reason) == len("openai: HTTP 401: ") + 500
    assert "busy" not in errors[0]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_a_failure_without_an_http_status_keeps_its_stack(caplog):
    models = _ScriptedModels("openai", RuntimeError("openai broke"))
    memory = _memory(models)

    with caplog.at_level(logging.WARNING, logger=_CATALOG_LOGGER):
        asyncio.run(memory.fill())

    (error,) = _errors(caplog)
    assert "openai: Traceback (most recent call last):" in error
    assert "RuntimeError: openai broke" in error
