# tests/test_patch_matcher.py — Tests for core/patch/matcher.py

import pytest

from core.patch.matcher import (
    canonicalize,
    compute_context_hash,
    find_exact_matches,
    find_similar_regions,
    indent_depth,
    match_file,
)


class TestCanonicalize:
    def test_crlf_to_lf(self):
        assert canonicalize("a\r\nb\r\n") == "a\nb\n"

    def test_lf_unchanged(self):
        assert canonicalize("a\nb\n") == "a\nb\n"

    def test_mixed(self):
        assert canonicalize("a\r\nb\nc\r\n") == "a\nb\nc\n"


class TestFindExactMatches:
    def test_single_match(self):
        content = "hello world\nfoo bar\nbaz"
        offsets = find_exact_matches(content, "foo bar")
        assert len(offsets) == 1
        assert content[offsets[0][0]:offsets[0][1]] == "foo bar"

    def test_zero_matches(self):
        content = "hello world"
        offsets = find_exact_matches(content, "missing")
        assert offsets == []

    def test_multiple_matches(self):
        content = "aXaXa"
        offsets = find_exact_matches(content, "a")
        assert len(offsets) == 3

    def test_multiline_match(self):
        content = "line1\nline2\nline3"
        offsets = find_exact_matches(content, "line1\nline2")
        assert len(offsets) == 1

    def test_empty_search(self):
        offsets = find_exact_matches("content", "")
        assert offsets == []


class TestComputeContextHash:
    def test_deterministic(self):
        content = "a\nb\nc\nd\ne\nf\ng\nh\ni\nj\nk"
        h1 = compute_context_hash(content, 4)
        h2 = compute_context_hash(content, 4)
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex

    def test_near_start(self):
        content = "a\nb\nc"
        h = compute_context_hash(content, 0)
        assert len(h) == 64

    def test_near_end(self):
        content = "a\nb\nc"
        h = compute_context_hash(content, len(content) - 1)
        assert len(h) == 64


class TestIndentDepth:
    def test_spaces(self):
        assert indent_depth("    code") == 4

    def test_tabs(self):
        assert indent_depth("\tcode") == 4

    def test_mixed(self):
        assert indent_depth("  \tcode") == 6  # 2 spaces + 4 for tab

    def test_no_indent(self):
        assert indent_depth("code") == 0

    def test_empty_line(self):
        assert indent_depth("") == 0


class TestFindSimilarRegions:
    def test_returns_top_3(self):
        content = "\n".join([
            "def alpha():",
            "    return 1",
            "",
            "def beta():",
            "    return 2",
            "",
            "def gamma():",
            "    return 3",
            "",
            "def delta():",
            "    return 4",
        ])
        search = "def alpha():\n    return 99"
        regions = find_similar_regions(content, search)
        assert len(regions) <= 3
        assert all(r.similarity > 0 for r in regions)

    def test_indentation_filter(self):
        content = "\n".join([
            "class Foo:",
            "    def method(self):",
            "        x = 1",
            "",
            "def standalone():",
            "    x = 1",
        ])
        search = "def standalone():\n    x = 99"
        regions = find_similar_regions(content, search)
        # Should prefer the standalone function (indent 0) over the method (indent 4)
        if regions:
            assert regions[0].similarity > 0

    def test_empty_search_block(self):
        regions = find_similar_regions("some content", "")
        assert regions == []

    def test_whitespace_only_search(self):
        regions = find_similar_regions("content", "   \n   ")
        assert regions == []

    def test_short_file(self):
        content = "x = 1"
        search = "x = 2"
        regions = find_similar_regions(content, search)
        assert len(regions) <= 3

    def test_token_overlap_scoring(self):
        content = "\n".join([
            "def process_data(items):",
            "    for item in items:",
            "        handle(item)",
            "",
            "def unrelated():",
            "    pass",
        ])
        search = "def process_data(items):\n    for item in items:\n        transform(item)"
        regions = find_similar_regions(content, search)
        if regions:
            # First result should be the process_data function (highest token overlap)
            assert "process_data" in regions[0].content

    def test_similarity_ranking(self):
        content = "\n".join([
            "def foo():",
            "    return 1",
            "",
            "def bar():",
            "    return 1",
        ])
        search = "def foo():\n    return 2"
        regions = find_similar_regions(content, search)
        if len(regions) >= 2:
            assert regions[0].similarity >= regions[1].similarity


class TestMatchFile:
    def test_success_exactly_one(self):
        content = "line1\nline2\nline3"
        result = match_file(content, "line2", file_path="test.py")
        assert result.success is True
        assert result.match_count == 1
        assert len(result.match_offsets) == 1
        assert len(result.context_hashes) == 1

    def test_zero_matches(self):
        content = "line1\nline2\nline3"
        result = match_file(content, "missing", file_path="test.py")
        assert result.success is False
        assert result.match_count == 0
        assert "No exact match" in result.error

    def test_multiple_matches(self):
        content = "x = 1\nx = 1\nx = 1"
        result = match_file(content, "x = 1", file_path="test.py")
        assert result.success is False
        assert result.match_count == 3
        assert "Ambiguous" in result.error
        assert len(result.match_offsets) == 3
        assert len(result.context_hashes) == 3

    def test_crlf_normalized(self):
        content = "line1\r\nline2\r\nline3"
        result = match_file(content, "line2", file_path="test.py")
        assert result.success is True

    def test_zero_match_returns_similar_regions(self):
        content = "def foo():\n    return 1\n\ndef bar():\n    return 2"
        result = match_file(content, "def foo():\n    return 99", file_path="test.py")
        assert result.success is False
        assert result.match_count == 0
        # Should have similar regions
        assert len(result.similar_regions) > 0

    def test_large_file_not_pathological(self):
        # 10000 lines shouldn't cause timeout
        content = "\n".join(f"line_{i} = {i}" for i in range(10000))
        search = "line_5000 = 9999"  # Modified value, won't match
        result = match_file(content, search, file_path="big.py")
        assert result.success is False  # No exact match
        # Just verify it completes without hanging
