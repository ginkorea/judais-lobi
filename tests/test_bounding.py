# tests/test_bounding.py — the one owner of "how much of a result a model sees"

"""One cut, one number, and every path that bounds a tool result using it.

Before ``core/bounding.py`` there were four implementations of the same
rule, all at ``32_768``, and they did not agree on what the rule was: the
mission cut head and tail with a marker naming the store handle, a role
cut the head only and appended a bare notice, and the tool-output record
spilled the whole thing to a log and showed the model **none** of it.
The number itself was written four times, so raising the budget in one
place raised it nowhere else.

These tests hold both halves of the fix: that the cut behaves the way the
best of the four behaved, and that no caller has quietly grown a second
opinion about the number or a second copy of the marker.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.bounding import HEAD_FRACTION, MAX_RESULT_BYTES, bound_result

REPO = Path(__file__).resolve().parent.parent

#: Every module that bounds a tool result or configures the bound. If a
#: fifth one appears, it belongs in this list and in the owner module.
CALLERS = [
    "core/kernel/budgets.py",
    "core/kernel/roles.py",
    "core/runtime/context_window.py",
    "core/runtime/mission.py",
    "core/tools/__init__.py",
    "core/tools/tool_output.py",
]


class TestTheCut:
    def test_a_result_inside_the_limit_is_returned_untouched(self):
        text, cut = bound_result("small", 1_000)
        assert text == "small"
        assert cut is False

    def test_a_result_exactly_at_the_limit_is_returned_untouched(self):
        text, cut = bound_result("x" * 100, 100)
        assert text == "x" * 100
        assert cut is False

    def test_both_ends_survive(self):
        """Head-only was the behaviour this replaced, and it threw away
        the half a governed view puts its totals in."""
        text, cut = bound_result("HEAD" + "x" * 5_000 + "TAIL", 500)
        assert cut is True
        assert text.startswith("HEAD")
        assert text.endswith("TAIL")

    def test_the_middle_is_gone(self):
        text, _ = bound_result("HEAD" + "m" * 5_000 + "TAIL", 500)
        assert text.count("m") < 500

    def test_the_split_follows_the_head_fraction(self):
        text, _ = bound_result("x" * 5_000, 500)
        head_n = int(500 * HEAD_FRACTION)
        assert f"{head_n} head + {500 - head_n} tail bytes" in text

    def test_the_marker_says_how_much_there_was(self):
        text, _ = bound_result("x" * 5_000, 500)
        assert "bytes of 5000." in text

    def test_the_marker_forbids_guessing_the_middle(self):
        """A silent cut is worse than an oversized paste: the model
        cannot see that anything went, so it narrates the figure it can
        still see or the one it remembers."""
        text, _ = bound_result("x" * 5_000, 500)
        assert "The middle is NOT shown and must not be guessed at." in text

    def test_the_caller_says_where_the_rest_lives(self):
        text, _ = bound_result("x" * 5_000, 500, where=" It is at /tmp/x.log.")
        assert "must not be guessed at. It is at /tmp/x.log.]" in text

    def test_with_no_where_the_marker_promises_nothing(self):
        """An empty *where* must not leave a dangling offer of a place to
        read the rest from, because for some callers there is none."""
        text, _ = bound_result("x" * 5_000, 500)
        assert "must not be guessed at.]" in text

    def test_a_zero_limit_means_no_bound(self):
        text, cut = bound_result("x" * 5_000, 0)
        assert text == "x" * 5_000
        assert cut is False

    def test_a_negative_limit_means_no_bound(self):
        text, cut = bound_result("x" * 5_000, -1)
        assert text == "x" * 5_000
        assert cut is False

    def test_the_kept_bytes_add_up_to_the_limit(self):
        text, _ = bound_result("x" * 5_000, 500)
        kept = text.split("\n… [")[0] + text.split("]\n", 1)[1]
        assert len(kept.encode("utf-8")) == 500

    def test_the_bound_counts_bytes_and_not_characters(self):
        """A budget spent on a context window is spent in bytes; a
        multi-byte character costs what it costs."""
        text, cut = bound_result("é" * 300, 500)
        assert cut is True, "600 bytes of text was let through a 500-byte cap"

    def test_a_cut_through_a_multibyte_character_does_not_raise(self):
        text, cut = bound_result("é" * 1_000, 501)
        assert cut is True
        assert "truncated" in text


class TestTheNumberHasOneOwner:
    def test_the_kernel_budget_defaults_to_it(self):
        from core.kernel.budgets import BudgetConfig
        assert BudgetConfig().max_tool_output_bytes_in_context == MAX_RESULT_BYTES

    def test_the_chat_context_config_defaults_to_it(self):
        from core.runtime.context_window import ContextConfig
        assert ContextConfig().max_tool_output_bytes_in_context == MAX_RESULT_BYTES

    def test_the_mission_runner_defaults_to_it(self):
        import core.runtime.mission as mission
        assert mission.MAX_RESULT_BYTES is MAX_RESULT_BYTES

    @pytest.mark.parametrize("path", CALLERS)
    def test_every_caller_takes_it_from_the_owner(self, path):
        """An import, not a mention: a docstring naming the owner while
        the module keeps its own copy is exactly the state this replaced."""
        assert re.search(
            r"^\s*from core\.bounding import ",
            (REPO / path).read_text(encoding="utf-8"),
            re.MULTILINE,
        ), f"{path} bounds a tool result without importing the owner"

    @pytest.mark.parametrize("path", CALLERS)
    def test_no_caller_spells_the_number_out_beside_the_budget(self, path):
        """A literal on the same line as the budget's name is a second
        declaration wearing a default's clothes."""
        for number, line in enumerate(
            (REPO / path).read_text(encoding="utf-8").splitlines(), 1
        ):
            if "max_tool_output_bytes_in_context" not in line:
                continue
            assert not re.search(r"\b32_?768\b", line), (
                f"{path}:{number} writes the cap out again: {line.strip()}"
            )

    def test_only_one_module_declares_the_constant(self):
        declaring = [
            path
            for path in (REPO / "core").rglob("*.py")
            if re.search(r"^MAX_RESULT_BYTES\s*=", path.read_text(encoding="utf-8"),
                         re.MULTILINE)
        ]
        assert [p.name for p in declaring] == ["bounding.py"]


class TestEveryPathThatBoundsAResultCallsIt:
    def test_the_mission_marker_is_the_shared_one(self):
        """The mission's ``_bound`` owns the sentence about the store and
        nothing else; a second copy of the marker would drift."""
        from core.runtime.mission import MissionRunner
        runner = MissionRunner(
            lambda _m: "", object(), ["t"], max_result_bytes=500, store_tool="",
        )
        body = "HEAD" + "x" * 5_000 + "TAIL"
        assert runner._bound(body) == bound_result(
            body, 500, where=" The rest is not retrievable in this mission.",
        )

    def test_the_mission_marker_names_the_handle_when_there_is_one(self):
        from core.runtime.mission import MissionRunner
        runner = MissionRunner(
            lambda _m: "", object(), ["t"], max_result_bytes=500,
        )
        text, cut = runner._bound("x" * 5_000, handle="r7")
        assert cut is True
        assert 'mission_result(handle="r7", path="...")' in text

    def test_a_role_trace_line_goes_through_it(self):
        from core.kernel.budgets import BudgetConfig
        from core.kernel.roles import RoleContext
        ctx = RoleContext(chat=lambda _m: "",
                          budget=BudgetConfig(max_tool_output_bytes_in_context=500))
        ctx.remember("HEAD" + "x" * 5_000 + "TAIL")
        assert ctx.trace[0] == bound_result("HEAD" + "x" * 5_000 + "TAIL", 500)[0]

    def test_an_oversized_tool_output_is_spilled_and_still_shown(self, tmp_path):
        """The record used to hand the model a path and zero bytes. An
        agent that cannot see whether the command worked spends a turn
        grepping a log to find out, or invents the answer."""
        from core.tools.tool_output import build_tool_output_record
        record = build_tool_output_record(
            "run_shell", (0, "HEAD" + "x" * 5_000 + "TAIL", ""),
            max_bytes=500, log_root=tmp_path,
        )
        assert record.stored_path is not None
        assert record.stored_path.read_text(encoding="utf-8").endswith("TAIL")
        assert "HEAD" in record.summary
        assert record.summary.endswith("TAIL")
        assert "must not be guessed at" in record.summary

    def test_the_oversized_record_still_names_the_log(self, tmp_path):
        from core.tools.tool_output import build_tool_output_record
        record = build_tool_output_record(
            "run_shell", (1, "x" * 5_000, ""), max_bytes=500, log_root=tmp_path,
        )
        assert f"Full log at: {record.stored_path}" in record.summary
        assert "Exit code: 1" in record.summary
        assert "Output exceeded budget (5000 bytes)." in record.summary

    def test_a_small_tool_output_is_not_spilled(self, tmp_path):
        from core.tools.tool_output import build_tool_output_record
        record = build_tool_output_record(
            "run_shell", (0, "ok", ""), max_bytes=500, log_root=tmp_path,
        )
        assert record.stored_path is None
        assert "truncated" not in record.summary
        assert record.summary.endswith("Output (2 bytes):\nok")

    def test_the_record_defaults_to_the_shared_cap(self, tmp_path):
        from core.tools.tool_output import build_tool_output_record
        record = build_tool_output_record(
            "run_shell", (0, "y" * (MAX_RESULT_BYTES + 1), ""), log_root=tmp_path,
        )
        assert record.stored_path is not None

    def test_the_spilled_log_is_replaced_and_never_truncated(self, tmp_path,
                                                             monkeypatch):
        """The spill is a store: the summary hands the agent a path and the
        agent reads it back, usually with a `grep` in the next turn. Written
        with a truncate-then-fill, the biggest outputs — the only ones that
        get here — had the longest window in which that path pointed at half
        a log, and half a log is what makes an agent invent the other half."""
        import os
        from core.tools.tool_output import build_tool_output_record

        replaced = []
        real = os.replace

        def watch(src, dst):
            replaced.append(Path(dst))
            return real(src, dst)

        monkeypatch.setattr(os, "replace", watch)
        record = build_tool_output_record(
            "run_shell", (0, "HEAD" + "x" * 5_000 + "TAIL", ""),
            max_bytes=500, log_root=tmp_path,
        )
        assert replaced == [record.stored_path]
        assert [p.name for p in tmp_path.iterdir()] == [record.stored_path.name]
