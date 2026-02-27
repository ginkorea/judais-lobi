# tests/test_critic_cache.py — Tests for core.critic.cache

from core.critic.cache import CriticCache
from core.critic.models import AggregatedCriticReport, CriticVerdict


def test_cache_put_get(tmp_path):
    cache = CriticCache(cache_dir=str(tmp_path))
    report = AggregatedCriticReport(consensus_verdict=CriticVerdict.APPROVE,
                                    payload_hash="abc")
    cache.put("abc", report)
    loaded = cache.get("abc")
    assert loaded is not None
    assert loaded.consensus_verdict == CriticVerdict.APPROVE


def test_cache_clear(tmp_path):
    cache = CriticCache(cache_dir=str(tmp_path))
    report = AggregatedCriticReport(consensus_verdict=CriticVerdict.CAUTION,
                                    payload_hash="abc")
    cache.put("abc", report)
    assert cache.clear() == 1
