"""Permission rule evaluation and tool filtering.

Rules are evaluated with last-match-wins semantics: the last matching rule in
the list takes effect. If no rule matches, the default action is "allow".
"""
# ComMent: permission 这里完全去掉，我发现我们并没有想清楚 permission 到底要怎么做
# TODO(Phase 3): 当前是简化版 MVP 方案，仅支持全局 tool 过滤。
# Phase 3 需要完整权限系统：
#   - path-level denies (e.g., *.env)
#   - "ask" action with user confirmation
#   - "always allow" persistence
#   - runtime permission checks during tool execution
import fnmatch
import logging
from typing import Any, Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PermissionRule(BaseModel):
    """A single permission rule mapping a tool name pattern to an action.

    Attributes:
        permission: Tool name or glob pattern (e.g., "*", "bash", "read").
        pattern: Resource pattern for future path-level rules. Defaults to "*".
        action: Whether to allow or deny matching tools.
    """

    permission: str
    pattern: str = "*"
    action: Literal["allow", "deny"]


def evaluate(tool_name: str, rules: list[PermissionRule]) -> Literal["allow", "deny"]:
    """Evaluate permission for a tool name against an ordered rule list.

    Uses last-match-wins semantics: the last rule whose permission field matches
    tool_name takes effect. If no rule matches, defaults to "allow".

    Args:
        tool_name: The name of the tool to evaluate.
        rules: Ordered list of permission rules.

    Returns:
        "allow" or "deny".
    """
    result: Literal["allow", "deny"] = "allow"
    for rule in rules:
        if fnmatch.fnmatch(tool_name, rule.permission):
            result = rule.action
    return result


def filter_tools(tools: list[Any], rules: list[PermissionRule]) -> list[Any]:
    """Return tools that are not globally denied by the rule set.

    Only removes a tool when the effective action for its name is "deny" with
    pattern="*" (i.e., the deny applies to all invocations of that tool). This
    mirrors opencode's pre-filtering behaviour: path-level denies are enforced
    at execution time, not at tool-list construction time.

    Args:
        tools: List of Strands tool objects (decorated functions).
        rules: Ordered list of permission rules.

    Returns:
        Filtered list of tools permitted by the rules.
    """
    filtered = []
    for tool_obj in tools:
        name = _tool_name(tool_obj)
        action = evaluate(name, rules)
        if action == "deny":
            logger.debug("tool=<%s> | tool removed by permission rules", name)
        else:
            filtered.append(tool_obj)
    return filtered


def _tool_name(tool_obj: Any) -> str:
    """Extract the tool name from a Strands tool object or plain function.

    Args:
        tool_obj: A Strands tool object or callable.

    Returns:
        The tool's name string.
    """
    # Strands @tool decorated functions expose TOOL_SPEC or tool_name attribute
    if hasattr(tool_obj, "TOOL_SPEC"):
        spec = tool_obj.TOOL_SPEC
        if isinstance(spec, dict):
            return str(spec.get("name", getattr(tool_obj, "__name__", str(tool_obj))))
    if hasattr(tool_obj, "tool_name"):
        return str(tool_obj.tool_name)
    if hasattr(tool_obj, "__name__"):
        return str(tool_obj.__name__)
    return str(tool_obj)
