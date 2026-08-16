# tests/test_critic_cache.py — Tests for core.critic.cache

import os

import pytest

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


class TestThePutIsAtomic:
    """A cached verdict is read back by a later run, so it is a store.

    `path.write_text` empties the file before it fills it: a `put` that died
    in between left a cache entry that parses as nothing under a hash the
    next run would look up, and `get` swallows the parse error and calls it
    a miss — the cheapest possible way to lose a critic pass and never say so.
    """

    def _explode(self, monkeypatch):
        def boom(src, dst):
            raise OSError("no space left on device")

        monkeypatch.setattr(os, "replace", boom)

    def test_a_failed_put_leaves_the_previous_verdict_whole(self, tmp_path,
                                                            monkeypatch):
        cache = CriticCache(cache_dir=str(tmp_path))
        cache.put("abc", AggregatedCriticReport(
            consensus_verdict=CriticVerdict.APPROVE, payload_hash="abc"))
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            cache.put("abc", AggregatedCriticReport(
                consensus_verdict=CriticVerdict.BLOCK, payload_hash="abc"))
        assert cache.get("abc").consensus_verdict == CriticVerdict.APPROVE

    def test_a_failed_put_leaves_no_staging_file_for_clear_to_miss(
            self, tmp_path, monkeypatch):
        cache = CriticCache(cache_dir=str(tmp_path))
        self._explode(monkeypatch)
        with pytest.raises(OSError):
            cache.put("abc", AggregatedCriticReport(
                consensus_verdict=CriticVerdict.APPROVE, payload_hash="abc"))
        assert list(tmp_path.iterdir()) == []

    def test_the_staging_file_is_not_one_clear_counts(self, tmp_path):
        """`clear` globs ``*.json``; the staging sibling is
        ``.abc.json.<rand>.tmp`` and would not be swept if one were left."""
        cache = CriticCache(cache_dir=str(tmp_path))
        cache.put("abc", AggregatedCriticReport(
            consensus_verdict=CriticVerdict.APPROVE, payload_hash="abc"))
        assert [p.name for p in tmp_path.iterdir()] == ["abc.json"]
        assert cache.clear() == 1
