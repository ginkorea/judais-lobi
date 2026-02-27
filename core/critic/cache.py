# core/critic/cache.py — SHA256-keyed cache for critic responses

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.critic.models import AggregatedCriticReport


class CriticCache:
    """File-based cache for AggregatedCriticReport.

    Cache directory: <repo_root>/.judais-lobi/cache/critic/
    """

    def __init__(self, cache_dir: Optional[str] = None):
        self._cache_dir = Path(cache_dir) if cache_dir else Path.cwd() / ".judais-lobi" / "cache" / "critic"

    def get(self, payload_hash: str) -> Optional[AggregatedCriticReport]:
        path = self._cache_dir / f"{payload_hash}.json"
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return AggregatedCriticReport.model_validate(raw)
        except Exception:
            return None

    def put(self, payload_hash: str, report: AggregatedCriticReport) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / f"{payload_hash}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path

    def clear(self) -> int:
        if not self._cache_dir.exists():
            return 0
        count = 0
        for item in self._cache_dir.glob("*.json"):
            try:
                item.unlink()
                count += 1
            except Exception:
                continue
        return count
