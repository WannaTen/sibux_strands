"""Task configuration helpers for MCP task-augmented execution."""

from datetime import timedelta

from typing_extensions import TypedDict

DEFAULT_TASK_TTL = timedelta(minutes=1)
DEFAULT_TASK_POLL_TIMEOUT = timedelta(minutes=5)


class TasksConfig(TypedDict, total=False):
    """Configuration for MCP task-augmented execution."""

    ttl: timedelta
    poll_timeout: timedelta


DEFAULT_TASK_CONFIG: TasksConfig = {
    "ttl": DEFAULT_TASK_TTL,
    "poll_timeout": DEFAULT_TASK_POLL_TIMEOUT,
}
