# tests/test_kv_prefix.py — Tests for KV-cacheable prefix builder

import pytest
from core.kv_prefix import build_static_prefix
from core.contracts.schemas import PolicyPack


def _describe(name):
    return {"name": name, "description": f"Description of {name}"}


class TestBuildStaticPrefix:
    def test_basic_prefix(self):
        prefix = build_static_prefix(
            system_message="You are a helpful agent.",
            tool_names=["run_shell_command"],
            describe_tool_fn=_describe,
        )
        assert "You are a helpful agent." in prefix
        assert "run_shell_command" in prefix
        assert "Description of run_shell_command" in prefix

    def test_empty_tools(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
        )
        assert "msg" in prefix
        assert "Available tools" not in prefix

    def test_multiple_tools_sorted(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=["z_tool", "a_tool"],
            describe_tool_fn=_describe,
        )
        a_pos = prefix.index("a_tool")
        z_pos = prefix.index("z_tool")
        assert a_pos < z_pos

    def test_with_policy(self):
        policy = PolicyPack(
            allowed_tools=["run_shell_command"],
            sandbox_backend="docker",
        )
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
            policy=policy,
        )
        assert "Session policy" in prefix
        assert "docker" in prefix

    def test_with_empty_policy(self):
        policy = PolicyPack()
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
            policy=policy,
        )
        assert "Session policy" in prefix
        assert "bwrap" in prefix

    def test_no_policy(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=[],
            describe_tool_fn=_describe,
            policy=None,
        )
        assert "Session policy" not in prefix

    def test_deterministic(self):
        """Same inputs produce same output (cacheable)."""
        args = dict(
            system_message="You are agent.",
            tool_names=["a", "b"],
            describe_tool_fn=_describe,
        )
        p1 = build_static_prefix(**args)
        p2 = build_static_prefix(**args)
        assert p1 == p2

    def test_sections_separated_by_double_newline(self):
        prefix = build_static_prefix(
            system_message="msg",
            tool_names=["tool"],
            describe_tool_fn=_describe,
        )
        assert "\n\n" in prefix
