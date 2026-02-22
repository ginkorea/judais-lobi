# tests/test_messages.py — Tests for message assembly functions

from core.runtime.messages import build_system_prompt, build_chat_context


class TestBuildSystemPrompt:
    def _describe(self, name):
        return {"description": f"desc for {name}"}

    def test_includes_system_message(self):
        result = build_system_prompt("You are a bot.", [], self._describe, [])
        assert "You are a bot." in result

    def test_includes_tool_descriptions(self):
        result = build_system_prompt(
            "sys", ["run_shell"], self._describe, []
        )
        assert "run_shell: desc for run_shell" in result

    def test_includes_examples(self):
        examples = [("How?", "Like this.")]
        result = build_system_prompt("sys", [], self._describe, examples)
        assert "User: How?" in result
        assert "Assistant: Like this." in result

    def test_handles_empty_tools_and_examples(self):
        result = build_system_prompt("sys", [], self._describe, [])
        assert "sys" in result
        assert "tools" in result.lower()

    def test_multiple_tools(self):
        result = build_system_prompt(
            "sys", ["tool_a", "tool_b"], self._describe, []
        )
        assert "tool_a: desc for tool_a" in result
        assert "tool_b: desc for tool_b" in result

    def test_multiple_examples(self):
        examples = [("Q1", "A1"), ("Q2", "A2")]
        result = build_system_prompt("sys", [], self._describe, examples)
        assert "User: Q1" in result
        assert "User: Q2" in result


class TestBuildChatContext:
    def test_replaces_system_message(self):
        history = [
            {"role": "system", "content": "old system"},
            {"role": "user", "content": "hello"},
        ]
        result = build_chat_context("new system prompt", history)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "new system prompt"

    def test_preserves_history(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "reply1"},
        ]
        result = build_chat_context("sys prompt", history)
        assert len(result) == 3
        assert result[1]["content"] == "msg1"
        assert result[2]["content"] == "reply1"

    def test_appends_tool_context(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = build_chat_context("sys prompt", history, invoked_tools=["run_shell"])
        assert "[Tool Context]" in result[0]["content"]
        assert "run_shell" in result[0]["content"]

    def test_no_tool_context_when_none(self):
        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
        result = build_chat_context("sys prompt", history, invoked_tools=None)
        assert "[Tool Context]" not in result[0]["content"]

    def test_empty_history_beyond_system(self):
        history = [{"role": "system", "content": "sys"}]
        result = build_chat_context("new sys", history)
        assert len(result) == 1
        assert result[0]["content"] == "new sys"
