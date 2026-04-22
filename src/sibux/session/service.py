"""Thin session lifecycle service for Sibux primary agents."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from strands.context_manager.sliding_window_context_manager import SlidingWindowContextManager
from strands.session import FileSessionManager
from strands.types.exceptions import SessionException
from strands.types.session import Session, SessionAgent, SessionType

from ..config.config import find_project_root, validate_agent_name
from ..event import SESSION_CREATED, SESSION_RESUMED, BusEvent, GlobalBus

logger = logging.getLogger(__name__)

DEFAULT_SESSION_STORAGE_DIR = Path(".sibux") / "session" / "strands"
DEFAULT_STATE_FILE = Path(".sibux") / "session" / "state.json"
STATE_VERSION = 1


@dataclass
class ActiveSession:
    """Active Sibux session metadata and manager.

    Attributes:
        session_id: Stable identifier for the active session.
        agent_name: Name of the primary agent using the session.
        agent_id: Stable Strands agent id used inside the session.
        storage_dir: Root directory for Strands file-backed session data.
        state_file: Path to the Sibux session state file.
        resumed: Whether this session was resumed from prior state.
        session_manager: Strands session manager for the active session.
        restore_error: Human-readable restore failure reason when session
            creation fell back to a new session.
    """

    session_id: str
    agent_name: str
    agent_id: str
    storage_dir: Path
    state_file: Path
    resumed: bool
    session_manager: FileSessionManager
    restore_error: str | None = None


@dataclass
class _StateRecord:
    version: int
    current_session_id: str
    agent: str
    updated_at: str


class SessionService:
    """Manage project-local Sibux sessions backed by Strands file storage."""

    def __init__(
        self,
        *,
        project_root: str | Path | None = None,
        storage_dir: str | Path = DEFAULT_SESSION_STORAGE_DIR,
        resume: Literal["last", "new"] = "last",
        global_bus: GlobalBus | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            project_root: Project root used to resolve session paths. Defaults
                to the resolved Sibux project root from ``find_project_root()``.
            storage_dir: Relative or absolute directory for Strands session
                files. The default matches the frozen Phase 2 contract.
            resume: Startup resume policy. ``"last"`` attempts to restore the
                most recent session for the current primary agent.
            global_bus: Optional process-wide event bus used to publish session
                lifecycle events.

        Raises:
            ValueError: When ``resume`` is not supported.
        """
        if resume not in {"last", "new"}:
            raise ValueError(f"resume=<{resume}> | unsupported resume policy")

        self._project_root = Path(project_root).resolve() if project_root is not None else find_project_root()
        self._storage_dir = self._resolve_storage_dir(storage_dir)
        self._state_file = (self._project_root / DEFAULT_STATE_FILE).resolve()
        self._resume = resume
        self._global_bus = global_bus if global_bus is not None else GlobalBus()
        self._current: ActiveSession | None = None

    def create_or_resume(self, *, agent_name: str) -> ActiveSession:
        """Create a new session or resume the most recent matching one.

        Args:
            agent_name: Primary agent name for the requested session.

        Returns:
            Active session metadata and the attached file session manager.
        """
        validated_agent_name = self._validate_agent_name(agent_name)

        if self._resume == "new":
            logger.debug(
                "agent=<%s>, resume=<%s> | creating new session by policy",
                validated_agent_name,
                self._resume,
            )
            return self._new_session(agent_name=validated_agent_name)

        try:
            state = self._load_state()
        except Exception as exc:
            logger.warning(
                "path=<%s>, error=<%s> | failed to load session state, creating new session", self._state_file, exc
            )
            return self._new_session(
                agent_name=validated_agent_name,
                restore_error=f"failed to load previous session state: {exc}",
            )

        if state is None:
            logger.debug("agent=<%s> | no session state found, creating new session", validated_agent_name)
            return self._new_session(agent_name=validated_agent_name)

        if state.agent != validated_agent_name:
            logger.debug(
                "agent=<%s>, state_agent=<%s> | state agent mismatch, creating new session",
                validated_agent_name,
                state.agent,
            )
            return self._new_session(agent_name=validated_agent_name)

        if not self._session_file(state.current_session_id).is_file():
            logger.debug(
                "agent=<%s>, session_id=<%s> | state points to missing session directory, creating new session",
                validated_agent_name,
                state.current_session_id,
            )
            return self._new_session(
                agent_name=validated_agent_name,
                restore_error=f"previous session '{state.current_session_id}' is missing on disk",
            )

        try:
            active_session = self._build_active_session(
                session_id=state.current_session_id,
                agent_name=validated_agent_name,
                resumed=True,
            )
            self._activate_session(active_session)
        except Exception as exc:
            logger.warning(
                "agent=<%s>, session_id=<%s>, error=<%s> | failed to resume session, creating new session",
                validated_agent_name,
                state.current_session_id,
                exc,
            )
            return self._new_session(
                agent_name=validated_agent_name,
                restore_error=f"failed to restore previous session '{state.current_session_id}': {exc}",
            )

        logger.debug("agent=<%s>, session_id=<%s> | resumed session", validated_agent_name, active_session.session_id)
        return active_session

    def new_session(self, *, agent_name: str) -> ActiveSession:
        """Create and activate a brand new session.

        Args:
            agent_name: Primary agent name for the new session.

        Returns:
            Active session metadata and the attached file session manager.
        """
        return self._new_session(agent_name=self._validate_agent_name(agent_name))

    def get_session(self, *, session_id: str) -> ActiveSession | None:
        """Load an existing session by id without changing current-session state."""
        if not self._session_file(session_id).is_file():
            return None

        session_manager = FileSessionManager(session_id=session_id, storage_dir=str(self._storage_dir))

        if session_manager.read_session(session_id) is None:
            return None

        agent_id = self._discover_primary_agent_id(session_id, session_manager)
        if agent_id is None:
            state = self._load_state()
            if state is not None and state.current_session_id == session_id:
                agent_id = state.agent

        if agent_id is None:
            logger.warning("session_id=<%s> | session exists but has no readable agent metadata", session_id)
            return None

        return self._build_active_session(
            session_id=session_id,
            agent_name=agent_id,
            resumed=True,
        )

    def _new_session(self, *, agent_name: str, restore_error: str | None = None) -> ActiveSession:
        active_session = self._build_active_session(
            session_id=self._generate_session_id(),
            agent_name=agent_name,
            resumed=False,
            restore_error=restore_error,
        )
        self._activate_session(active_session)
        logger.debug("agent=<%s>, session_id=<%s> | created new session", agent_name, active_session.session_id)
        return active_session

    def current(self) -> ActiveSession | None:
        """Return the currently active session for this service instance."""
        return self._current

    def _build_active_session(
        self,
        *,
        session_id: str,
        agent_name: str,
        resumed: bool,
        restore_error: str | None = None,
    ) -> ActiveSession:
        session_manager = FileSessionManager(session_id=session_id, storage_dir=str(self._storage_dir))
        return ActiveSession(
            session_id=session_id,
            agent_name=agent_name,
            agent_id=agent_name,
            storage_dir=self._storage_dir,
            state_file=self._state_file,
            resumed=resumed,
            session_manager=session_manager,
            restore_error=restore_error,
        )

    def _set_current(self, active_session: ActiveSession) -> None:
        self._write_state(active_session)
        self._current = active_session

    def _activate_session(self, active_session: ActiveSession) -> None:
        """Persist and publish the newly active session."""
        self._ensure_session_metadata(active_session)
        self._set_current(active_session)
        self.publish_session_event(active_session)

    def _write_state(self, active_session: ActiveSession) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "version": STATE_VERSION,
            "current_session_id": active_session.session_id,
            "agent": active_session.agent_name,
            "updated_at": _utc_now(),
        }
        tmp_file = self._state_file.with_name(f"{self._state_file.name}.tmp")
        with open(tmp_file, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.replace(tmp_file, self._state_file)

    def _load_state(self) -> _StateRecord | None:
        if not self._state_file.exists():
            return None

        with open(self._state_file, encoding="utf-8") as fh:
            raw_state: object = json.load(fh)

        if not isinstance(raw_state, dict):
            raise ValueError("session state must be a JSON object")

        version = raw_state.get("version")
        current_session_id = raw_state.get("current_session_id")
        agent = raw_state.get("agent")
        updated_at = raw_state.get("updated_at")

        if type(version) is not int or version != STATE_VERSION:
            raise ValueError(f"session state version must equal {STATE_VERSION}")
        if not isinstance(current_session_id, str) or not current_session_id:
            raise ValueError("session state current_session_id must be a non-empty string")
        if not isinstance(agent, str) or not agent:
            raise ValueError("session state agent must be a non-empty string")
        if not isinstance(updated_at, str) or not updated_at:
            raise ValueError("session state updated_at must be a non-empty string")

        return _StateRecord(
            version=version,
            current_session_id=current_session_id,
            agent=self._validate_agent_name(agent),
            updated_at=updated_at,
        )

    def _resolve_storage_dir(self, storage_dir: str | Path) -> Path:
        storage_path = Path(storage_dir)
        if not storage_path.is_absolute():
            storage_path = self._project_root / storage_path
        return storage_path.resolve()

    def _discover_primary_agent_id(self, session_id: str, session_manager: FileSessionManager) -> str | None:
        """Find the primary agent id recorded inside one session directory."""
        agents_dir = self._session_dir(session_id) / "agents"
        if not agents_dir.is_dir():
            return None

        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir() or not agent_dir.name.startswith("agent_"):
                continue

            agent_id = agent_dir.name.removeprefix("agent_")
            if not agent_id:
                continue

            try:
                session_agent = session_manager.read_agent(session_id=session_id, agent_id=agent_id)
            except SessionException:
                logger.warning(
                    "session_id=<%s>, agent_id=<%s> | failed to read session agent metadata",
                    session_id,
                    agent_id,
                    exc_info=True,
                )
                continue

            if session_agent is not None:
                return self._validate_agent_name(session_agent.agent_id)

        return None

    def _session_dir(self, session_id: str) -> Path:
        return self._storage_dir / f"session_{session_id}"

    def _session_file(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "session.json"

    def _generate_session_id(self) -> str:
        return f"sibux_{uuid4().hex}"

    def _validate_agent_name(self, agent_name: str) -> str:
        return validate_agent_name(agent_name)

    def _ensure_session_metadata(self, active_session: ActiveSession) -> None:
        """Persist the minimal session and agent metadata needed for later restores."""
        session_manager = active_session.session_manager

        if session_manager.read_session(active_session.session_id) is None:
            session_manager.create_session(
                Session(
                    session_id=active_session.session_id,
                    session_type=SessionType.AGENT,
                )
            )

        if session_manager.read_agent(active_session.session_id, active_session.agent_id) is None:
            session_manager.create_agent(
                active_session.session_id,
                SessionAgent(
                    agent_id=active_session.agent_id,
                    state={},
                    context_manager_state=SlidingWindowContextManager().get_state(),
                ),
            )

    def publish_session_event(self, active_session: ActiveSession) -> None:
        """Publish the session lifecycle event for the given active session."""
        event_type = SESSION_RESUMED if active_session.resumed else SESSION_CREATED
        self._global_bus.emit(
            BusEvent(
                type=event_type,
                session_id=active_session.session_id,
                timestamp=_utc_now(),
                payload={"agent_name": active_session.agent_name},
            )
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
