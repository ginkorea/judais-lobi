# tests/test_judge_gpu_profile.py — Tests for core.judge.gpu_profile

import pytest
from dataclasses import FrozenInstanceError

from core.judge.gpu_profile import GPUProfile, detect_profile


class TestGPUProfile:
    def test_defaults(self):
        p = GPUProfile()
        assert p.cpu_only is True
        assert p.max_concurrent == 1
        assert p.device_name == "cpu"

    def test_frozen(self):
        p = GPUProfile()
        with pytest.raises(FrozenInstanceError):
            p.cpu_only = False

    def test_custom_values(self):
        p = GPUProfile(cpu_only=False, max_concurrent=4, device_name="cuda:0")
        assert p.cpu_only is False
        assert p.max_concurrent == 4
        assert p.device_name == "cuda:0"


class TestDetectProfile:
    def test_returns_gpu_profile(self):
        p = detect_profile()
        assert isinstance(p, GPUProfile)

    def test_stub_returns_cpu(self):
        p = detect_profile()
        assert p.cpu_only is True
        assert p.max_concurrent == 1
