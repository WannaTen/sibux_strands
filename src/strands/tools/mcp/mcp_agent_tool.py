"""MCP tool wrapper that adapts MCP tools to the AgentTool interface."""

from typing import TYPE_CHECKING, Any

from mcp.types import Tool as MCPTool
from typing_extensions import override

from ...types._events import ToolResultEvent
from ...types.tools import AgentTool, ToolGenerator, ToolSpec, ToolUse

if TYPE_CHECKING:
    from .mcp_client import MCPClient


class MCPAgentTool(AgentTool):
    """Adapter exposing an MCP tool through the standard AgentTool interface."""

    def __init__(self, mcp_tool: MCPTool, client: "MCPClient", name_override: str | None = None) -> None:
        """Initialize the wrapper.

        Args:
            mcp_tool: The underlying MCP tool description.
            client: MCP client used to invoke the remote tool.
            name_override: Optional public tool name override.
        """
        super().__init__()
        self.mcp_tool = mcp_tool
        self._client = client
        self._tool_name = name_override or mcp_tool.name

    @property
    @override
    def tool_name(self) -> str:
        """Return the public tool name."""
        return self._tool_name

    @property
    @override
    def tool_spec(self) -> ToolSpec:
        """Return the tool specification expected by Strands models."""
        return {
            "name": self.tool_name,
            "description": self.mcp_tool.description or "",
            "inputSchema": {"json": self.mcp_tool.inputSchema or {"type": "object", "properties": {}}},
        }

    @property
    @override
    def tool_type(self) -> str:
        """Return the tool type identifier."""
        return "mcp"

    @override
    async def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any) -> ToolGenerator:
        """Invoke the underlying MCP tool and yield its final result."""
        result = await self._client.call_tool_async(
            tool_use_id=tool_use["toolUseId"],
            name=self.mcp_tool.name,
            arguments=tool_use.get("input"),
        )
        yield ToolResultEvent(result)
