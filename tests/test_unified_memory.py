# tests/test_unified_memory.py

import pytest
import numpy as np

from core.memory.memory import UnifiedMemory


class TestShortTermMemory:
    def test_add_and_load_short(self, memory):
        memory.add_short("user", "hello")
        memory.add_short("assistant", "hi there")
        rows = memory.load_short(n=10)
        assert len(rows) == 2
        assert rows[0]["role"] == "user"
        assert rows[0]["content"] == "hello"
        assert rows[1]["role"] == "assistant"

    def test_load_short_respects_limit(self, memory):
        for i in range(10):
            memory.add_short("user", f"msg {i}")
        rows = memory.load_short(n=3)
        assert len(rows) == 3

    def test_reset_short(self, memory):
        memory.add_short("user", "something")
        memory.reset_short()
        rows = memory.load_short()
        assert len(rows) == 0

    def test_load_short_empty(self, memory):
        rows = memory.load_short()
        assert rows == []


class TestLongTermMemory:
    def test_add_and_search_long(self, memory):
        memory.add_long("user", "The capital of France is Paris")
        memory.add_long("assistant", "Paris is a beautiful city")
        results = memory.search_long("What is the capital of France?", top_k=2)
        assert len(results) > 0
        assert all("content" in r for r in results)

    def test_search_long_empty(self, memory):
        results = memory.search_long("anything")
        assert results == []

    def test_purge_long(self, memory):
        memory.add_long("user", "remember this")
        memory.purge_long()
        assert memory.long_index is None
        assert memory.long_id_map == []
        results = memory.search_long("remember")
        assert results == []


class TestAdventures:
    def test_add_and_list_adventures(self, memory):
        memory.add_adventure("test prompt", "print('hi')", "hi", "python", True)
        memory.add_adventure("test 2", "ls -la", "files", "shell", False)
        adventures = memory.list_adventures(n=10)
        assert len(adventures) == 2
        assert adventures[0]["prompt"] == "test prompt"
        assert adventures[0]["success"] is True
        assert adventures[1]["success"] is False

    def test_list_adventures_empty(self, memory):
        assert memory.list_adventures() == []


class TestModelLock:
    def test_model_lock_mismatch_raises(self, tmp_path, fake_embedding_client):
        db = tmp_path / "lock_test.db"
        UnifiedMemory(db, model="text-embedding-3-large", embedding_client=fake_embedding_client)
        with pytest.raises(RuntimeError, match="Embedding model mismatch"):
            UnifiedMemory(db, model="text-embedding-3-small", embedding_client=fake_embedding_client)

    def test_model_lock_same_model_ok(self, tmp_path, fake_embedding_client):
        db = tmp_path / "lock_test2.db"
        UnifiedMemory(db, model="text-embedding-3-large", embedding_client=fake_embedding_client)
        mem2 = UnifiedMemory(db, model="text-embedding-3-large", embedding_client=fake_embedding_client)
        assert mem2.model == "text-embedding-3-large"


class TestIndexRebuild:
    def test_rebuild_long_index_from_db(self, tmp_path, fake_embedding_client):
        db = tmp_path / "rebuild_test.db"
        mem1 = UnifiedMemory(db, embedding_client=fake_embedding_client)
        mem1.add_long("user", "fact one")
        mem1.add_long("user", "fact two")

        # Create a new instance — it should rebuild from DB
        mem2 = UnifiedMemory(db, embedding_client=fake_embedding_client)
        assert mem2.long_index is not None
        assert len(mem2.long_id_map) == 2
