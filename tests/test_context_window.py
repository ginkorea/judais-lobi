# tests/test_context_window.py — Context window manager tests

from types import SimpleNamespace

from core.runtime.context_window import ContextConfig, ContextWindowManager
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
