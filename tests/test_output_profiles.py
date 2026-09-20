"""Task-sized output allowances share the input fitter's reserve."""

import pytest

from core.runtime.backends.local_backend import LocalBackend, ServedModel
from core.runtime.context_window import MissionWindow


@pytest.fixture(autouse=True)
def clean_output_configuration(monkeypatch):
    monkeypatch.delenv("JUDAIS_LOBI_MAX_OUTPUT_TOKENS", raising=False)
    monkeypatch.delenv("JUDAIS_LOBI_OUTPUT_PROFILE", raising=False)


def local(profile=None, capacity=131072, **kwargs):
    client = LocalBackend(output_profile=profile, **kwargs)
    client._probed = ServedModel("m", max_model_len=capacity, reachable=True, served=("m",))
    return client


@pytest.mark.parametrize("profile,target", [(None, 8192), ("standard", 8192),
                                          ("synthesis", 16384), ("extended", 32768)])
def test_profile_is_the_wire_and_context_reserve(profile, target):
    client = local(profile)
    fitted = MissionWindow(client=client)
    assert client.output_bound == client.capabilities.max_output_tokens == target
    assert fitted.request_budget([])["output_reserve_tokens"] == target
    assert fitted.limit_tokens == 131072 - target


@pytest.mark.parametrize("capacity,expected", [(8192, 4096), (16384, 8192), (65536, 32768)])
def test_profile_leaves_input_room_on_smaller_endpoints(capacity, expected):
    client = local("extended", capacity)
    assert client.output_bound == expected
    assert MissionWindow(client=client).limit_tokens == capacity - expected


def test_explicit_numeric_ceiling_beats_profile_and_environment(monkeypatch):
    monkeypatch.setenv("JUDAIS_LOBI_OUTPUT_PROFILE", "extended")
    monkeypatch.setenv("JUDAIS_LOBI_MAX_OUTPUT_TOKENS", "20000")
    assert local("synthesis").output_bound == 20000
    assert local("extended", max_output_tokens=3000).output_bound == 3000


def test_environment_is_per_backend_not_shared_mutable_state(monkeypatch):
    monkeypatch.setenv("JUDAIS_LOBI_OUTPUT_PROFILE", "synthesis")
    first = local()
    monkeypatch.setenv("JUDAIS_LOBI_OUTPUT_PROFILE", "extended")
    second = local()
    assert first.output_bound == 16384
    assert second.output_bound == 32768


def test_unrecognized_profile_does_not_turn_off_inference():
    assert local("typo").output_bound == 8192


def test_unknown_capacity_does_not_become_a_claimed_capacity():
    client = local("synthesis", None)
    assert client.output_bound == 16384
    assert client.capabilities.max_context_tokens is None
