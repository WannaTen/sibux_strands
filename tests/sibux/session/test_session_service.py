"""Tests for the Sibux session service."""

import json
import shutil
from pathlib import Path

import pytest

from sibux.session import SessionService
from strands.session import FileSessionManager


class TestSessionService:
    def test_current_returns_none_before_create(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        assert service.current() is None

    def test_create_or_resume_creates_new_session(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        active_session = service.create_or_resume(agent_name="build")

        assert active_session.session_id.startswith("sibux_")
        assert active_session.agent_name == "build"
        assert active_session.agent_id == "build"
        assert active_session.storage_dir == (tmp_path / ".sibux" / "session" / "strands").resolve()
        assert active_session.state_file == (tmp_path / ".sibux" / "session" / "state.json").resolve()
        assert active_session.resumed is False
        assert isinstance(active_session.session_manager, FileSessionManager)
        assert active_session.storage_dir.is_relative_to((tmp_path / ".sibux" / "session").resolve())
        assert active_session.state_file.is_relative_to((tmp_path / ".sibux" / "session").resolve())
        assert service.current() is active_session

        state = json.loads(active_session.state_file.read_text(encoding="utf-8"))
        assert state["version"] == 1
        assert state["current_session_id"] == active_session.session_id
        assert state["agent"] == "build"
        assert (active_session.storage_dir / f"session_{active_session.session_id}").is_dir()

    def test_default_project_root_uses_find_project_root_from_nested_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"default_agent": "build"}), encoding="utf-8")
        nested = tmp_path / "repo" / "src"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        active_session = SessionService().create_or_resume(agent_name="build")

        assert active_session.storage_dir == (tmp_path / ".sibux" / "session" / "strands").resolve()
        assert active_session.state_file == (tmp_path / ".sibux" / "session" / "state.json").resolve()

    def test_relative_storage_dir_is_resolved_from_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sibux_dir = tmp_path / ".sibux"
        sibux_dir.mkdir()
        (sibux_dir / "config.json").write_text(json.dumps({"default_agent": "build"}), encoding="utf-8")
        nested = tmp_path / "repo" / "src"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        active_session = SessionService(storage_dir=".custom/session").create_or_resume(agent_name="build")

        assert active_session.storage_dir == (tmp_path / ".custom" / "session").resolve()

    def test_create_or_resume_resumes_same_session_for_same_agent(self, tmp_path: Path) -> None:
        first_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")

        service = SessionService(project_root=tmp_path)
        resumed_session = service.create_or_resume(agent_name="build")

        assert resumed_session.session_id == first_session.session_id
        assert resumed_session.agent_id == "build"
        assert resumed_session.resumed is True
        assert service.current() is resumed_session

    def test_create_or_resume_creates_new_session_for_other_agent(self, tmp_path: Path) -> None:
        first_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")

        other_agent_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="plan")

        assert other_agent_session.session_id != first_session.session_id
        assert other_agent_session.agent_name == "plan"
        assert other_agent_session.agent_id == "plan"
        assert other_agent_session.resumed is False

        state_file = tmp_path / ".sibux" / "session" / "state.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["agent"] == "plan"
        assert state["current_session_id"] == other_agent_session.session_id

    def test_create_or_resume_creates_new_session_when_session_dir_missing(self, tmp_path: Path) -> None:
        first_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")
        shutil.rmtree(first_session.storage_dir / f"session_{first_session.session_id}")

        next_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")

        assert next_session.session_id != first_session.session_id
        assert next_session.resumed is False

    def test_new_session_always_generates_new_session_id(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        first_session = service.new_session(agent_name="build")
        second_session = service.new_session(agent_name="build")

        assert first_session.session_id != second_session.session_id
        assert first_session.resumed is False
        assert second_session.resumed is False
        assert service.current() is second_session

    def test_create_or_resume_with_resume_new_always_creates_new_session(self, tmp_path: Path) -> None:
        first_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")

        second_session = SessionService(project_root=tmp_path, resume="new").create_or_resume(agent_name="build")

        assert second_session.session_id != first_session.session_id
        assert second_session.resumed is False

    def test_create_or_resume_rejects_invalid_agent_name(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        with pytest.raises(ValueError, match="agent_id=review/build \\| id cannot contain path separators"):
            service.create_or_resume(agent_name="review/build")

    def test_new_session_rejects_invalid_agent_name(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        with pytest.raises(ValueError, match="agent_id=review/build \\| id cannot contain path separators"):
            service.new_session(agent_name="review/build")

    def test_create_or_resume_rejects_empty_agent_name(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        with pytest.raises(ValueError, match="agent name must be a non-empty, non-whitespace string"):
            service.create_or_resume(agent_name="")

    def test_create_or_resume_rejects_whitespace_agent_name(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        with pytest.raises(ValueError, match="agent name must be a non-empty, non-whitespace string"):
            service.create_or_resume(agent_name="   ")

    def test_new_session_rejects_empty_agent_name(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        with pytest.raises(ValueError, match="agent name must be a non-empty, non-whitespace string"):
            service.new_session(agent_name="")

    def test_new_session_rejects_whitespace_agent_name(self, tmp_path: Path) -> None:
        service = SessionService(project_root=tmp_path)

        with pytest.raises(ValueError, match="agent name must be a non-empty, non-whitespace string"):
            service.new_session(agent_name="   ")

    def test_create_or_resume_falls_back_to_new_session_when_state_file_is_invalid(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".sibux" / "session" / "state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("{invalid json", encoding="utf-8")

        active_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")

        assert active_session.session_id.startswith("sibux_")
        assert active_session.resumed is False

    def test_create_or_resume_falls_back_to_new_session_when_existing_session_is_corrupted(
        self, tmp_path: Path
    ) -> None:
        broken_session_id = "sibux_broken"
        state_file = tmp_path / ".sibux" / "session" / "state.json"
        storage_dir = tmp_path / ".sibux" / "session" / "strands"
        session_dir = storage_dir / f"session_{broken_session_id}"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text("{invalid json", encoding="utf-8")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "current_session_id": broken_session_id,
                    "agent": "build",
                    "updated_at": "2026-03-29T12:34:56Z",
                }
            ),
            encoding="utf-8",
        )

        active_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")

        assert active_session.session_id != broken_session_id
        assert active_session.resumed is False

    def test_create_or_resume_falls_back_to_new_session_when_state_version_mismatches(self, tmp_path: Path) -> None:
        first_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")
        state_file = tmp_path / ".sibux" / "session" / "state.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        state["version"] = 999
        state_file.write_text(json.dumps(state), encoding="utf-8")

        next_session = SessionService(project_root=tmp_path).create_or_resume(agent_name="build")
        next_state = json.loads(state_file.read_text(encoding="utf-8"))

        assert next_session.session_id != first_session.session_id
        assert next_session.resumed is False
        assert next_state["version"] == 1
