# tests/test_one_gpu_profile.py — there is exactly one GPUProfile

"""The consolidation, held in place.

There were two `GPUProfile` types. `core/judge/gpu_profile.py` was a
stub that always reported ``cpu_only=True, max_concurrent=1`` and had
**no caller anywhere in the package** — only a re-export and its own
test.  `core/runtime/gpu.py` reads ``JUDAIS_LOBI_VRAM_GB`` and then
torch, and feeds ``ContextWindowManager``.

The stub was deleted rather than implemented.  Two types with one name
is a coin flip at every import site, and the honest question the judge
would have asked it — how many candidates may run at once — is a
property of the *serving layer* (vLLM batches; a hosted provider is
network-bound), not of the client's device list.  Reimplementing it
would have produced a second answer to a question this process cannot
answer.

This file exists so a third one is a test failure and not a discovery.
"""

import ast
import pathlib

import pytest

CORE = pathlib.Path(__file__).resolve().parent.parent / "core"


def _modules_defining(class_name: str):
    found = []
    for path in CORE.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                found.append(path.relative_to(CORE.parent).as_posix())
    return sorted(found)


class TestExactlyOne:
    def test_only_one_module_defines_gpuprofile(self):
        assert _modules_defining("GPUProfile") == ["core/runtime/gpu.py"]

    def test_the_survivor_is_importable_where_it_always_was(self):
        from core.runtime import GPUProfile, detect_gpu_profile

        assert GPUProfile is not None
        assert callable(detect_gpu_profile)

    def test_the_judge_no_longer_offers_one(self):
        import core.judge as judge

        assert "GPUProfile" not in judge.__all__
        assert "detect_profile" not in judge.__all__
        with pytest.raises(AttributeError):
            judge.GPUProfile

    def test_the_deleted_module_is_gone(self):
        with pytest.raises(ImportError):
            import core.judge.gpu_profile  # noqa: F401

    def test_the_judge_package_still_imports(self):
        """Deleting a lazy export must not break the eager ones."""
        from core.judge import CompositeJudge, TierVerdict

        assert CompositeJudge is not None
        assert TierVerdict is not None


class TestTheSurvivorIsHonest:
    """It reports what it found, and says nothing when it found nothing."""

    def test_no_gpu_reports_zero_rather_than_a_guess(self, monkeypatch):
        import core.runtime.gpu as gpu

        monkeypatch.delenv("JUDAIS_LOBI_VRAM_GB", raising=False)
        monkeypatch.setitem(__import__("sys").modules, "torch", None)
        profile = gpu.detect_gpu_profile()
        assert profile.device_count == 0
        assert profile.total_vram_gb == 0.0

    def test_no_vram_means_no_context_cap_not_a_default_one(self):
        from core.runtime.gpu import vram_to_context_cap

        assert vram_to_context_cap(0.0) is None
