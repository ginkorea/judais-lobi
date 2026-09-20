"""Reasoning exhausted the completion budget, not the JSON parser."""

from dataclasses import replace

import pytest

from core.contracts.schemas import PolicyPack
from core.runtime.backends.base import Usage
from core.runtime.backends.local_backend import LocalBackend, ServedModel
from core.runtime.context_window import ContextConfig, ContextWindowManager, MissionWindow
from core.runtime.run import Bounds, Model, NO_SUPERVISOR, Observer, Personality, Run, Store, ToolPlane
from core.tools.bus import ToolBus
from core.tools.capability import CapabilityEngine
from core.unified_client import UnifiedClient


def backend(monkeypatch, **kwargs):
    monkeypatch.delenv("JUDAIS_LOBI_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("JUDAIS_LOBI_OUTPUT_PROFILE", raising=False)
    local = LocalBackend(**kwargs)
    local._probed = ServedModel("m", max_model_len=131072, reachable=True, served=("m",))
    return local


def exhausted(tokens=8192, prompt=18000, finish="length"):
    return {"prompt_tokens": prompt, "completion_tokens": tokens,
            "total_tokens": prompt + tokens, "finish_reason": finish}


def test_budget_recovery_and_context_reserve_match(monkeypatch):
    local = backend(monkeypatch)
    client = UnifiedClient(backend=local)
    window = MissionWindow(client=client)
    assert window.profile.max_output_tokens == 8192
    raised = client.recover_output_budget(exhausted())
    assert raised == 16384
    window.reserve_output_tokens(raised)
    assert local.output_bound == local.capabilities.max_output_tokens == 16384
    assert window.limit_tokens == 131072 - 16384


def test_operator_ceiling_is_not_raised(monkeypatch):
    local = backend(monkeypatch, max_output_tokens=4096)
    assert local.recover_output_budget(exhausted()) is None
    monkeypatch.setenv("JUDAIS_LOBI_MAX_OUTPUT_TOKENS", "4096")
    local = LocalBackend()
    assert local.recover_output_budget(exhausted()) is None


def test_no_unmeasured_or_unbounded_retry(monkeypatch):
    local = backend(monkeypatch)
    assert local.recover_output_budget(exhausted(finish="stop")) is None
    assert local.recover_output_budget({"finish_reason": "length"}) is None
    local._probed = ServedModel("m", reachable=True, served=("m",))
    assert local.recover_output_budget(exhausted()) is None


@pytest.mark.parametrize("config", [ContextConfig(), ContextConfig(max_context_tokens=65536),
                                   ContextConfig(model_overrides={"m": 65536})])
def test_output_reserve_still_matches_when_context_probe_has_no_length(monkeypatch, config):
    local = backend(monkeypatch, max_output_tokens=20000)
    local._probed = ServedModel("m", reachable=True, served=("m",))
    profile = ContextWindowManager(config).resolve_profile("local", "m", local.capabilities)
    assert profile.max_output_tokens == 20000


def test_recovery_has_headroom_and_a_finite_ceiling(monkeypatch):
    local = backend(monkeypatch)
    local._probed = replace(local._probed, max_model_len=23000)
    assert local.recover_output_budget(exhausted()) is None
    local._probed = replace(local._probed, max_model_len=131072)
    assert local.recover_output_budget(exhausted()) == 16384
    assert local.recover_output_budget(exhausted(16384)) == 32768
    assert local.recover_output_budget(exhausted(32768)) is None


@pytest.mark.parametrize("protocol", ["json", "native"])
def test_empty_length_is_retried_once_and_every_call_is_billed(monkeypatch, protocol):
    local = backend(monkeypatch)
    window = MissionWindow(client=local)
    seen = []
    events = []
    budget_at_call = []

    def ask(messages):
        seen.append(messages)
        budget_at_call.append((local.output_bound, window.profile.max_output_tokens))
        local.last_usage = Usage.from_payload(exhausted(local.output_bound), "length")
        return ""

    run = Run(Personality(), ToolPlane(bus=ToolBus(capability_engine=CapabilityEngine(
        PolicyPack(allowed_scopes=["*"]))), offered=[]),
        Bounds(max_steps=6, supervisor=NO_SUPERVISOR), Store(), Observer(events.append),
        Model(ask=ask, protocol=protocol, window=window,
              usage_fn=lambda: local.last_usage,
              recover_output_budget=local.recover_output_budget))
    transcript = run.run("Answer the question.")
    assert len(seen) == 2
    assert budget_at_call == [(8192, 8192), (16384, 16384)]
    assert transcript.outcome == "incomplete"
    assert "output-token budget" in transcript.steps[-1].error
    assert "not a JSON-format error" in transcript.steps[-1].error
    rejected = [event for event in events if event["event"] == "reply_rejected"]
    assert [event["usage"]["completion_tokens"] for event in rejected] == [8192, 16384]


def test_successful_recovery_returns_the_actual_answer(monkeypatch):
    local = backend(monkeypatch)
    window = MissionWindow(client=local)
    calls = []

    def ask(messages):
        calls.append(messages)
        if len(calls) == 1:
            local.last_usage = Usage.from_payload(exhausted(), "length")
            return ""
        local.last_usage = Usage.from_payload({"prompt_tokens": 100, "completion_tokens": 20})
        return '{"answer":"A real answer."}'

    run = Run(Personality(), ToolPlane(bus=ToolBus(), offered=[]),
              Bounds(max_steps=4, supervisor=NO_SUPERVISOR), Store(), Observer(),
              Model(ask=ask, window=window, usage_fn=lambda: local.last_usage,
                    recover_output_budget=local.recover_output_budget))
    assert run.run("Explain.").answer == "A real answer."
    assert len(calls) == 2


def test_no_retry_without_a_bound_recovery_callback(monkeypatch):
    local = backend(monkeypatch)
    calls = []

    def ask(messages):
        calls.append(messages)
        local.last_usage = Usage.from_payload(exhausted(), "length")
        return ""

    run = Run(Personality(), ToolPlane(bus=ToolBus(), offered=[]),
              Bounds(max_steps=4, supervisor=NO_SUPERVISOR), Store(), Observer(),
              Model(ask=ask, usage_fn=lambda: local.last_usage))
    result = run.run("Explain.")
    assert result.outcome == "incomplete"
    assert len(calls) == 1
