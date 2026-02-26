# core/judge/gpu_profile.py — Hardware profile stub for candidate concurrency
#
# Phase 7.2: Stub that always returns CPU-only profile.
# Real hardware detection deferred to a future phase.

from dataclasses import dataclass


@dataclass(frozen=True)
class GPUProfile:
    """Hardware profile for budgeting candidate concurrency."""
    cpu_only: bool = True
    max_concurrent: int = 1
    device_name: str = "cpu"


def detect_profile() -> GPUProfile:
    """Detect hardware profile. Stub: always returns CPU-only."""
    return GPUProfile()
