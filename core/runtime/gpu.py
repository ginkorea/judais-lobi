# core/runtime/gpu.py — GPU profile detection (best-effort)

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class GPUProfile:
    device_count: int = 0
    total_vram_gb: float = 0.0
    device_names: List[str] = None


def detect_gpu_profile() -> GPUProfile:
    """Best-effort GPU detection. Returns CPU profile when unavailable."""
    env = os.getenv("JUDAIS_LOBI_VRAM_GB")
    if env:
        try:
            vram = float(env)
            return GPUProfile(device_count=1, total_vram_gb=vram, device_names=["env"])
        except Exception:
            pass

    try:
        import torch
        if torch.cuda.is_available():
            count = torch.cuda.device_count()
            names: List[str] = []
            total = 0.0
            for idx in range(count):
                props = torch.cuda.get_device_properties(idx)
                names.append(getattr(props, "name", f"cuda:{idx}"))
                total += float(getattr(props, "total_memory", 0)) / (1024 ** 3)
            return GPUProfile(device_count=count, total_vram_gb=total, device_names=names)
    except Exception:
        pass

    return GPUProfile(device_count=0, total_vram_gb=0.0, device_names=[])


def vram_to_context_cap(total_vram_gb: float) -> Optional[int]:
    """Return a conservative context cap based on VRAM size."""
    if total_vram_gb <= 0:
        return None
    if total_vram_gb < 8:
        return 4096
    if total_vram_gb < 12:
        return 8192
    if total_vram_gb < 24:
        return 16384
    if total_vram_gb < 48:
        return 32768
    if total_vram_gb < 80:
        return 65536
    return 131072
