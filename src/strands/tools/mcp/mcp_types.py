"""Shared MCP-specific type definitions."""

from contextlib import AbstractAsyncContextManager
from typing import Any

from typing_extensions import NotRequired, TypedDict

from ...types.tools import ToolResultContent, ToolResultStatus

MCPTransport = AbstractAsyncContextManager[tuple[Any, Any] | tuple[Any, Any, Any]]
"""Async context manager yielding MCP transport read/write streams."""


class MCPToolResult(TypedDict):
    """Tool result returned from an MCP-backed tool invocation."""

    content: list[ToolResultContent]
    status: ToolResultStatus
    toolUseId: str
    metadata: NotRequired[dict[str, Any]]
    structuredContent: NotRequired[dict[str, Any]]
