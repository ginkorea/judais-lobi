# tests/test_replay_needs_no_key.py — a replay asks no model, so it needs no key
"""CI proved it on a runner with no provider key: `judais --replay <run>` died
with `Missing OPENAI_API_KEY` before reading a byte of the recording, because
the hosted backends demanded their key at CONSTRUCTION and a backend is
constructed for every run. The key is a fact about asking, and a replay never
asks. So: the three hosted backends resolve their SDK client — and demand the
key — at the first `chat`, and a replay of a recorded run completes with every
provider variable unset."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
KEYS = ("OPENAI_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY", "LOCAL_API_KEY", "LOCAL_API_BASE", "LOCAL_MODEL")


class TestTheHostedBackendsDemandTheKeyWhenAsked:

    def test_openai_constructs_without_a_key_and_refuses_on_use(self,
                                                              monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from core.runtime.backends.openai_backend import OpenAIBackend
        backend = OpenAIBackend()                    # no raise
        with pytest.raises(RuntimeError, match="Missing OPENAI_API_KEY"):
            backend.client

    def test_mistral_constructs_without_a_key_and_refuses_on_use(self,
                                                               monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        from core.runtime.backends.mistral_backend import MistralBackend
        backend = MistralBackend()                   # no raise
        with pytest.raises(RuntimeError, match="Missing MISTRAL_API_KEY"):
            backend._headers()

    def test_anthropic_constructs_without_a_key_and_refuses_on_use(
            self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from core.runtime.backends.anthropic_backend import AnthropicBackend
        backend = AnthropicBackend()                 # no raise
        with pytest.raises(RuntimeError, match="Missing ANTHROPIC_API_KEY"):
            backend.client


class TestAReplayNeedsNoKey:
    """The committed json corpus replays through the real CLI in a subprocess
    whose environment carries no provider variable at all — no key, no
    endpoint, no model name — and completes with `mission_finished`."""

    def test_the_corpus_replays_with_every_provider_variable_unset(
            self, tmp_path):
        env = {k: v for k, v in os.environ.items() if k not in KEYS}
        env["JUDAIS_LOBI_RUNS"] = str(REPO / "tests" / "fixtures" / "runs")
        env["PYTHONPATH"] = str(REPO)
        events = tmp_path / "events.ndjson"
        child = subprocess.run(
            [sys.executable, str(REPO / "main.py"), "judais", "--mission", "--replay",
             "run_corpusjson-0001", "--events", str(events), "--no-stream"],
            cwd=str(tmp_path), env=env, capture_output=True, text=True,
            timeout=300,
        )
        assert child.returncode == 0, child.stderr[-2000:]
        assert "mission_finished" in events.read_text()
