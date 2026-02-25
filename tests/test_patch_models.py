# tests/test_patch_models.py — Tests for core/patch/models.py

import pytest

from core.patch.models import FileMatchResult, PatchResult, SimilarRegion


class TestSimilarRegion:
    def test_construction(self):
        r = SimilarRegion(
            line_start=1, line_end=5, content="hello",
            similarity=0.8, indent_depth=4,
        )
        assert r.line_start == 1
        assert r.line_end == 5
        assert r.content == "hello"
        assert r.similarity == 0.8
        assert r.indent_depth == 4

    def test_zero_similarity(self):
        r = SimilarRegion(
            line_start=1, line_end=1, content="",
            similarity=0.0, indent_depth=0,
        )
        assert r.similarity == 0.0


class TestFileMatchResult:
    def test_defaults(self):
        r = FileMatchResult(file_path="a.py", action="modify", success=True)
        assert r.match_count == 0
        assert r.match_offsets == []
        assert r.context_hashes == []
        assert r.similar_regions == []
        assert r.error == ""

    def test_to_dict(self):
        r = FileMatchResult(
            file_path="a.py", action="modify", success=True,
            match_count=1, match_offsets=[(0, 10)],
            context_hashes=["abc123"],
        )
        d = r.to_dict()
        assert d["file_path"] == "a.py"
        assert d["success"] is True
        assert d["match_offsets"] == [(0, 10)]
        assert d["similar_regions"] == []

    def test_to_dict_with_similar_regions(self):
        region = SimilarRegion(
            line_start=2, line_end=4, content="code",
            similarity=0.7, indent_depth=0,
        )
        r = FileMatchResult(
            file_path="b.py", action="modify", success=False,
            similar_regions=[region],
        )
        d = r.to_dict()
        assert len(d["similar_regions"]) == 1
        assert d["similar_regions"][0]["similarity"] == 0.7


class TestPatchResult:
    def test_defaults(self):
        r = PatchResult(success=True)
        assert r.file_results == []
        assert r.worktree_path == ""
        assert r.diff == ""
        assert r.error == ""

    def test_to_dict(self):
        fr = FileMatchResult(file_path="x.py", action="create", success=True)
        r = PatchResult(success=True, file_results=[fr], worktree_path="/tmp/wt")
        d = r.to_dict()
        assert d["success"] is True
        assert len(d["file_results"]) == 1
        assert d["worktree_path"] == "/tmp/wt"
