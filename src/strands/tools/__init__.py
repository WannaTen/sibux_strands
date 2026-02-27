"""Agent tool interfaces and utilities.

This module provides the core functionality for creating, managing, and executing tools through agents.
"""

from typing import Any

from pydantic import BaseModel

from .decorator import tool
from .tool_provider import ToolProvider
from .tools import InvalidToolUseNameException, PythonAgentTool, normalize_schema, normalize_tool_spec
from ..types.tools import ToolSpec


def convert_pydantic_to_tool_spec(model: type[BaseModel]) -> ToolSpec:
    """Convert a Pydantic model class to a ToolSpec for structured output.

    Args:
        model: A Pydantic BaseModel subclass.

    Returns:
        A ToolSpec derived from the model's JSON schema.
    """
    schema = model.model_json_schema()
    return ToolSpec(
        name=model.__name__,
        description=schema.get("description", model.__name__),
        inputSchema={"json": schema},
    )


__all__ = [
    "tool",
    "PythonAgentTool",
    "InvalidToolUseNameException",
    "normalize_schema",
    "normalize_tool_spec",
    "convert_pydantic_to_tool_spec",
    "ToolProvider",
]
