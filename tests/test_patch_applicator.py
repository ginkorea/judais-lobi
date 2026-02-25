# tests/test_patch_applicator.py — Tests for core/patch/applicator.py

import os
import stat
from pathlib import Path

import pytest

from core.contracts.schemas import FilePatch
from core.patch.applicator import (
    PathJailError,
    apply_create,
    apply_delete,
    apply_modify,
    apply_patch,
    jail_path,
)


class TestJailPath:
    def test_valid_relative_path(self, tmp_path):
        result = jail_path("src/main.py", tmp_path)
        assert result == (tmp_path / "src" / "main.py").resolve()

    def test_absolute_path_rejected(self, tmp_path):
        with pytest.raises(PathJailError, match="Absolute path"):
            jail_path("/etc/passwd", tmp_path)

    def test_traversal_rejected(self, tmp_path):
        with pytest.raises(PathJailError, match="Path traversal"):
            jail_path("../escape.py", tmp_path)

    def test_deep_traversal_rejected(self, tmp_path):
        with pytest.raises(PathJailError, match="Path traversal"):
            jail_path("src/../../escape.py", tmp_path)

    def test_empty_path_rejected(self, tmp_path):
        with pytest.raises(PathJailError, match="Empty file path"):
            jail_path("", tmp_path)


class TestApplyModify:
    def test_successful_replacement(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("def old():\n    return 1\n")
        result = apply_modify(f, "def old():\n    return 1\n", "def new():\n    return 2\n")
        assert result.success is True
        assert f.read_text() == "def new():\n    return 2\n"

    def test_zero_matches(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("hello world\n")
        result = apply_modify(f, "missing text", "replacement")
        assert result.success is False
        assert result.match_count == 0

    def test_multiple_matches(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1\nx = 1\n")
        result = apply_modify(f, "x = 1", "x = 2")
        assert result.success is False
        assert result.match_count == 2

    def test_crlf_normalized(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_bytes(b"line1\r\nline2\r\n")
        result = apply_modify(f, "line1\nline2\n", "new1\nnew2\n")
        assert result.success is True
        assert f.read_text() == "new1\nnew2\n"

    def test_empty_replace_deletes_text(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("keep\nremove this\nkeep too\n")
        result = apply_modify(f, "remove this\n", "")
        assert result.success is True
        assert f.read_text() == "keep\nkeep too\n"

    def test_preserves_file_mode(self, tmp_path):
        f = tmp_path / "script.sh"
        f.write_text("#!/bin/bash\necho old\n")
        os.chmod(f, 0o755)
        result = apply_modify(f, "echo old", "echo new")
        assert result.success is True
        mode = os.stat(f).st_mode
        assert mode & stat.S_IXUSR  # Still executable

    def test_preserves_indentation(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("    indented = True\n")
        result = apply_modify(f, "    indented = True", "    indented = False")
        assert result.success is True
        assert f.read_text() == "    indented = False\n"

    def test_file_not_found(self, tmp_path):
        f = tmp_path / "missing.py"
        result = apply_modify(f, "old", "new")
        assert result.success is False
        assert "does not exist" in result.error


class TestApplyCreate:
    def test_new_file(self, tmp_path):
        f = tmp_path / "new.py"
        result = apply_create(f, "# new file\n")
        assert result.success is True
        assert f.read_text() == "# new file\n"

    def test_already_exists(self, tmp_path):
        f = tmp_path / "existing.py"
        f.write_text("old content")
        result = apply_create(f, "new content")
        assert result.success is False
        assert "already exists" in result.error

    def test_parent_dirs_created(self, tmp_path):
        f = tmp_path / "deep" / "nested" / "file.py"
        result = apply_create(f, "content")
        assert result.success is True
        assert f.exists()

    def test_lf_endings(self, tmp_path):
        f = tmp_path / "test.py"
        result = apply_create(f, "line1\r\nline2\r\n")
        assert result.success is True
        assert f.read_text() == "line1\nline2\n"


class TestApplyDelete:
    def test_delete_file(self, tmp_path):
        f = tmp_path / "old.py"
        f.write_text("to be deleted")
        result = apply_delete(f)
        assert result.success is True
        assert not f.exists()

    def test_delete_missing(self, tmp_path):
        f = tmp_path / "missing.py"
        result = apply_delete(f)
        assert result.success is False
        assert "does not exist" in result.error


class TestApplyPatch:
    def test_dispatch_modify(self, tmp_path):
        (tmp_path / "a.py").write_text("old\n")
        patch = FilePatch(file_path="a.py", search_block="old\n",
                          replace_block="new\n", action="modify")
        result = apply_patch(tmp_path, patch)
        assert result.success is True

    def test_dispatch_create(self, tmp_path):
        patch = FilePatch(file_path="new.py", replace_block="content",
                          action="create")
        result = apply_patch(tmp_path, patch)
        assert result.success is True

    def test_dispatch_delete(self, tmp_path):
        (tmp_path / "old.py").write_text("x")
        patch = FilePatch(file_path="old.py", action="delete")
        result = apply_patch(tmp_path, patch)
        assert result.success is True

    def test_unknown_action(self, tmp_path):
        patch = FilePatch(file_path="x.py", action="unknown")
        result = apply_patch(tmp_path, patch)
        assert result.success is False
        assert "Unknown action" in result.error

    def test_path_jail_traversal(self, tmp_path):
        patch = FilePatch(file_path="../escape.py", action="create",
                          replace_block="bad")
        result = apply_patch(tmp_path, patch)
        assert result.success is False
        assert "Path traversal" in result.error

    def test_path_jail_absolute(self, tmp_path):
        patch = FilePatch(file_path="/etc/passwd", action="delete")
        result = apply_patch(tmp_path, patch)
        assert result.success is False
        assert "Absolute path" in result.error
