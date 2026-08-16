# tests/test_context_window.py — Context window manager tests

from types import SimpleNamespace

from core.runtime.context_window import (
    ContextConfig, ContextWindowManager, MissionWindow,
)
from core.runtime.gpu import GPUProfile


def test_context_compaction():
    cfg = ContextConfig(max_context_tokens=200, max_output_tokens=20, min_tail_messages=2, max_summary_chars=200)
    mgr = ContextWindowManager(config=cfg)
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u" * 400},
        {"role": "assistant", "content": "a" * 400},
        {"role": "user", "content": "tail"},
        {"role": "assistant", "content": "tail2"},
    ]
    messages, stats = mgr.build_messages(
        system_prompt="sys",
        history=history,
        invoked_tools=None,
        provider="openai",
        model="gpt-4o",
        backend_caps=None,
    )
    assert stats.was_compacted is True
    assert any("Context summary" in m["content"] for m in messages)


def test_gpu_cap_applies_for_local():
    cfg = ContextConfig()
    mgr = ContextWindowManager(config=cfg)
    profile = mgr._resolve_profile(
        provider="local",
        model="gpt-4o",
        backend_caps=None,
        gpu_profile=GPUProfile(device_count=1, total_vram_gb=4.0, device_names=["gpu0"]),
    )
    assert profile.max_context_tokens == 4096


def test_backend_caps_override():
    cfg = ContextConfig()
    mgr = ContextWindowManager(config=cfg)
    caps = SimpleNamespace(max_context_tokens=7777, max_output_tokens=333)
    profile = mgr._resolve_profile(
        provider="openai",
        model="gpt-4o",
        backend_caps=caps,
        gpu_profile=None,
    )
    assert profile.max_context_tokens == 7777
    assert profile.max_output_tokens == 333


def test_a_backend_that_states_only_a_context_length_is_still_believed():
    """`max_model_len` is the one number here that was measured.

    A vLLM endpoint reports its served model's context length and says
    nothing about an output reserve, which is the shape `LocalBackend`
    hands over. Discarding the probe for want of the second number meant
    falling back to a 32,768 provider default on an 8,192 server: the
    request that 400s, chosen over the number that would have prevented it.
    """
    mgr = ContextWindowManager(config=ContextConfig())
    caps = SimpleNamespace(max_context_tokens=8192, max_output_tokens=None)
    profile = mgr.resolve_profile(
        provider="local", model="gpt-oss-20b", backend_caps=caps,
    )
    assert (profile.max_context_tokens, profile.source) == (8192, "backend")


# ── the mission's window ─────────────────────────────────────────────────────


def _mission_messages(rounds, *, pinned=2, result_chars=400):
    """A pinned prefix, then *rounds* of (model decision, tool result)."""
    messages = [{"role": "system", "content": "persona + catalogue"}]
    messages += [{"role": "user", "content": f"seeded {i}"}
                 for i in range(pinned - 2)]
    messages.append({"role": "user", "content": "the objective"})
    for i in range(rounds):
        messages.append({"role": "assistant", "content": f'{{"tool": "t{i}"}}'})
        messages.append({"role": "user", "content": f"Result of t{i}: "
                                                    + "x" * result_chars})
    return messages


def _window(limit_tokens=600, output_tokens=100):
    return MissionWindow(config=ContextConfig(
        max_context_tokens=limit_tokens, max_output_tokens=output_tokens))


def test_a_conversation_that_fits_is_handed_back_untouched():
    window = _window()
    messages = _mission_messages(1, result_chars=20)
    fitted, compaction = window.fit(messages, pinned=2)
    assert compaction is None
    assert fitted == messages


def test_the_conversation_that_goes_out_is_under_the_limit():
    window = _window()
    fitted, compaction = window.fit(_mission_messages(8), pinned=2)
    assert compaction is not None
    assert window.estimate(fitted) <= window.limit_tokens


def test_the_pinned_prefix_survives():
    """The catalogue, the seeded turns and the objective are the mission.

    An agent that has forgotten which tools exist, or what it was asked, is
    a worse failure than the one being fixed.
    """
    messages = _mission_messages(8, pinned=4)
    fitted, _ = _window().fit(messages, pinned=4)
    assert fitted[:4] == messages[:4]


def test_the_newest_round_trip_survives():
    """The latest result is what the next reply is made out of."""
    messages = _mission_messages(8)
    fitted, _ = _window().fit(messages, pinned=2)
    assert fitted[-2:] == messages[-2:]


def test_the_oldest_round_trips_are_the_ones_that_go():
    messages = _mission_messages(8)
    fitted, compaction = _window().fit(messages, pinned=2)
    kept = "".join(m["content"] for m in fitted)
    assert "Result of t0" not in kept
    assert "Result of t7" in kept
    assert compaction.dropped_turns >= 1
    assert compaction.freed_chars > 0


def test_what_was_dropped_is_replaced_by_a_notice():
    """A silently shortened conversation is worse than a short one: the
    model cannot see anything is missing and re-runs a call it made."""
    fitted, _ = _window().fit(_mission_messages(8), pinned=2)
    assert any("[context]" in m["content"] for m in fitted)


def test_the_tail_never_starts_with_a_stranded_result():
    """Half a round trip is a result whose call is gone."""
    fitted, _ = _window().fit(_mission_messages(8), pinned=2)
    assert fitted[3]["role"] == "assistant"


def test_a_second_compaction_does_not_strand_a_result():
    """The notice the first compaction left is itself a user turn.

    So the oldest pair the second one takes is (notice, decision), and
    what a stride of two would leave at the front is a result belonging to
    a call the model can no longer see it made.
    """
    window = _window()
    once, _ = window.fit(_mission_messages(8), pinned=2)
    grown = once + _mission_messages(4)[2:]
    fitted, compaction = window.fit(grown, pinned=2)
    assert compaction is not None
    assert fitted[3]["role"] == "assistant"
    assert sum(1 for m in fitted if "[context]" in m["content"]) == 1


def test_the_newest_round_trip_survives_a_window_it_cannot_fit():
    """The floor is a whole round trip, and it is a floor and not a target.

    A pinned prefix bigger than the window is a deployment problem, not a
    reason to send the model a result whose call it cannot see or to
    refuse the mission outright. What is returned is as short as this can
    make it, and the record says it did not get under the line.
    """
    window = MissionWindow(config=ContextConfig(
        max_context_tokens=300, max_output_tokens=100))
    messages = _mission_messages(8)
    fitted, compaction = window.fit(messages, pinned=2)
    assert fitted[-2:] == messages[-2:]
    assert compaction.tokens_after > compaction.limit_tokens


def test_the_record_counts_turns_and_messages_separately():
    _, compaction = _window().fit(_mission_messages(8), pinned=2)
    assert compaction.dropped_messages == 2 * compaction.dropped_turns
    record = compaction.as_record()
    assert record["tokens_before"] > record["tokens_after"]
    assert record["limit_tokens"] == _window().limit_tokens


def test_no_reported_context_size_falls_back_to_the_declared_default():
    """Never a guess and never unbounded: the module's own fallback."""
    window = MissionWindow(provider="", model="", config=ContextConfig())
    assert window.profile.source == "fallback"
    assert window.limit_tokens == 16384 - 2048


def test_a_client_whose_capabilities_raise_is_not_a_mission_that_failed():
    class Unreachable:
        @property
        def capabilities(self):
            raise RuntimeError("no route to host")

    window = MissionWindow(provider="local", model="gpt-oss-20b",
                           client=Unreachable(), config=ContextConfig(),
                           gpu_profile=GPUProfile(device_count=0,
                                                  total_vram_gb=0.0,
                                                  device_names=[]))
    assert window.limit_tokens > 0


def test_the_backend_is_asked_once_and_only_when_needed():
    """Reading `capabilities` on the local backend is a GET against a server
    that may still be loading weights; constructing a runner must not wait
    on it."""
    class Counting:
        def __init__(self):
            self.asks = 0

        @property
        def capabilities(self):
            self.asks += 1
            return SimpleNamespace(max_context_tokens=8192,
                                   max_output_tokens=512)

    client = Counting()
    window = MissionWindow(provider="local", model="m", client=client,
                           config=ContextConfig())
    assert client.asks == 0
    window.fit(_mission_messages(1), pinned=2)
    window.fit(_mission_messages(2), pinned=2)
    assert client.asks == 1
