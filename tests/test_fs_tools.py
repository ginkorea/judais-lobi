# tests/test_fs_tools.py — FsTool tests

import json
import pytest
from core.tools.fs_tools import FsTool


@pytest.fixture
def fs():
    return FsTool()


class TestFsRead:
    def test_read_existing_file(self, fs, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        rc, out, err = fs("read", str(f))
        assert rc == 0
        assert out == "hello world"
        assert err == ""

    def test_read_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("read", str(tmp_path / "nope.txt"))
        assert rc == 1
        assert "not found" in err.lower()

    def test_read_directory_fails(self, fs, tmp_path):
        rc, out, err = fs("read", str(tmp_path))
        assert rc == 1
        assert "not a file" in err.lower()


class TestFsWrite:
    def test_write_new_file(self, fs, tmp_path):
        target = tmp_path / "out.txt"
        rc, out, err = fs("write", str(target), content="data")
        assert rc == 0
        assert "4 bytes" in out
        assert target.read_text() == "data"

    def test_write_creates_parents(self, fs, tmp_path):
        target = tmp_path / "a" / "b" / "c.txt"
        rc, out, err = fs("write", str(target), content="nested")
        assert rc == 0
        assert target.read_text() == "nested"

    def test_write_overwrites(self, fs, tmp_path):
        target = tmp_path / "f.txt"
        target.write_text("old")
        fs("write", str(target), content="new")
        assert target.read_text() == "new"


class TestFsDelete:
    def test_delete_file(self, fs, tmp_path):
        f = tmp_path / "doomed.txt"
        f.write_text("bye")
        rc, out, err = fs("delete", str(f))
        assert rc == 0
        assert not f.exists()

    def test_delete_directory(self, fs, tmp_path):
        d = tmp_path / "doomed_dir"
        d.mkdir()
        (d / "child.txt").write_text("x")
        rc, out, err = fs("delete", str(d))
        assert rc == 0
        assert not d.exists()

    def test_delete_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("delete", str(tmp_path / "nope"))
        assert rc == 1
        assert "not found" in err.lower()


class TestFsList:
    def test_list_directory(self, fs, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        rc, out, err = fs("list", str(tmp_path))
        assert rc == 0
        assert "a.txt" in out
        assert "b.txt" in out

    def test_list_recursive(self, fs, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("d")
        rc, out, err = fs("list", str(tmp_path), recursive=True)
        assert rc == 0
        assert "deep.txt" in out

    def test_list_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("list", str(tmp_path / "nope"))
        assert rc == 1

    def test_list_file_fails(self, fs, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("x")
        rc, out, err = fs("list", str(f))
        assert rc == 1


class TestFsStat:
    def test_stat_file(self, fs, tmp_path):
        f = tmp_path / "s.txt"
        f.write_text("hello")
        rc, out, err = fs("stat", str(f))
        assert rc == 0
        info = json.loads(out)
        assert info["size"] == 5
        assert info["is_file"] is True
        assert info["is_dir"] is False

    def test_stat_directory(self, fs, tmp_path):
        rc, out, err = fs("stat", str(tmp_path))
        assert rc == 0
        info = json.loads(out)
        assert info["is_dir"] is True

    def test_stat_nonexistent(self, fs, tmp_path):
        rc, out, err = fs("stat", str(tmp_path / "nope"))
        assert rc == 1


class TestFsUnknownAction:
    def test_unknown_action(self, fs, tmp_path):
        rc, out, err = fs("explode", str(tmp_path))
        assert rc == 1
        assert "unknown" in err.lower()
