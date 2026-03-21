"""Tests for the built-in tools."""

from pathlib import Path
from unittest.mock import patch

import pytest

from sibux.tools.bash import bash
from sibux.tools.edit import edit
from sibux.tools.glob_tool import glob_tool
from sibux.tools.grep import grep
from sibux.tools.read import read
from sibux.tools.truncation import MAX_BYTES, MAX_LINES, truncate
from sibux.tools.write import write


class TestTruncation:
    def test_short_text_unchanged(self) -> None:
        text = "hello\nworld"
        assert truncate(text) == text

    def test_long_text_truncated(self) -> None:
        lines = [f"line {i}" for i in range(MAX_LINES + 10)]
        text = "\n".join(lines)
        result = truncate(text)
        assert "truncated" in result
        assert len(result.splitlines()) <= MAX_LINES + 2  # content lines + notice

    def test_large_bytes_truncated(self) -> None:
        text = "x" * (MAX_BYTES + 1)
        result = truncate(text)
        assert "truncated" in result


class TestBash:
    def test_echo_command(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        result = bash.__wrapped__("echo hello")  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert "hello" in result["content"][0]["text"]

    def test_nonzero_exit_still_success_status(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        result = bash.__wrapped__("exit 1")  # type: ignore[attr-defined]
        # We return success even on non-zero exit; output is captured
        assert result["status"] == "success"

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        result = bash.__wrapped__("sleep 10", timeout=1)  # type: ignore[attr-defined]
        assert result["status"] == "error"
        assert "timed out" in result["content"][0]["text"]

    def test_stderr_captured(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.chdir(tmp_path)
        result = bash.__wrapped__("echo err >&2")  # type: ignore[attr-defined]
        assert "err" in result["content"][0]["text"]


class TestRead:
    def test_read_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\n")
        result = read.__wrapped__(str(f))  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert "line1" in result["content"][0]["text"]

    def test_missing_file(self, tmp_path: Path) -> None:
        result = read.__wrapped__(str(tmp_path / "missing.txt"))  # type: ignore[attr-defined]
        assert result["status"] == "error"

    def test_offset_and_limit(self, tmp_path: Path) -> None:
        f = tmp_path / "lines.txt"
        f.write_text("\n".join(f"line{i}" for i in range(10)))
        result = read.__wrapped__(str(f), offset=2, limit=3)  # type: ignore[attr-defined]
        text = result["content"][0]["text"]
        assert "line2" in text
        assert "line4" in text
        assert "line5" not in text

    def test_directory_returns_error(self, tmp_path: Path) -> None:
        result = read.__wrapped__(str(tmp_path))  # type: ignore[attr-defined]
        assert result["status"] == "error"


class TestEdit:
    def test_simple_replace(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello world")
        result = edit.__wrapped__(str(f), "hello", "goodbye")  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert f.read_text() == "goodbye world"

    def test_multiple_occurrences_without_replace_all(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("foo foo foo")
        result = edit.__wrapped__(str(f), "foo", "bar")  # type: ignore[attr-defined]
        assert result["status"] == "error"
        assert "3 times" in result["content"][0]["text"]

    def test_replace_all(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("foo foo foo")
        result = edit.__wrapped__(str(f), "foo", "bar", replace_all=True)  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert f.read_text() == "bar bar bar"

    def test_missing_old_string(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("hello world")
        result = edit.__wrapped__(str(f), "xyz", "abc")  # type: ignore[attr-defined]
        assert result["status"] == "error"

    def test_missing_file(self, tmp_path: Path) -> None:
        result = edit.__wrapped__(str(tmp_path / "no.txt"), "a", "b")  # type: ignore[attr-defined]
        assert result["status"] == "error"


class TestWrite:
    def test_write_new_file(self, tmp_path: Path) -> None:
        f = tmp_path / "new.txt"
        result = write.__wrapped__(str(f), "content")  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert f.read_text() == "content"

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        f = tmp_path / "a" / "b" / "c.txt"
        result = write.__wrapped__(str(f), "hello")  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert f.read_text() == "hello"

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("old")
        write.__wrapped__(str(f), "new")  # type: ignore[attr-defined]
        assert f.read_text() == "new"


class TestGlobTool:
    def test_finds_matching_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")
        (tmp_path / "c.txt").write_text("")
        result = glob_tool.__wrapped__("*.py")  # type: ignore[attr-defined]
        assert result["status"] == "success"
        text = result["content"][0]["text"]
        assert "a.py" in text
        assert "b.py" in text
        assert "c.txt" not in text

    def test_no_matches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = glob_tool.__wrapped__("*.xyz")  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert "no matches" in result["content"][0]["text"]

    def test_recursive_pattern(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.py").write_text("")
        result = glob_tool.__wrapped__("**/*.py")  # type: ignore[attr-defined]
        assert "deep.py" in result["content"][0]["text"]


class TestGrep:
    def test_finds_pattern(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    pass\n")
        result = grep.__wrapped__("def hello", str(tmp_path))  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert "def hello" in result["content"][0]["text"]

    def test_no_matches(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("nothing here\n")
        result = grep.__wrapped__("xyz_not_present", str(tmp_path))  # type: ignore[attr-defined]
        assert result["status"] == "success"
        assert "no matches" in result["content"][0]["text"]

    def test_invalid_regex(self, tmp_path: Path) -> None:
        with patch("sibux.tools.grep._find_rg", return_value=""):
            result = grep.__wrapped__("[invalid", str(tmp_path))  # type: ignore[attr-defined]
        assert result["status"] == "error"

    def test_include_filter(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("target\n")
        (tmp_path / "b.txt").write_text("target\n")
        with patch("sibux.tools.grep._find_rg", return_value=""):
            result = grep.__wrapped__("target", str(tmp_path), include="*.py")  # type: ignore[attr-defined]
        text = result["content"][0]["text"]
        assert "a.py" in text
        assert "b.txt" not in text
