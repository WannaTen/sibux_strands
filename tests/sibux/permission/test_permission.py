"""Tests for the permission module."""

from sibux.permission.permission import PermissionRule, evaluate, filter_tools


def make_rule(permission: str, action: str, pattern: str = "*") -> PermissionRule:
    return PermissionRule(permission=permission, pattern=pattern, action=action)


class TestEvaluate:
    def test_default_allow_when_no_rules(self) -> None:
        assert evaluate("bash", []) == "allow"

    def test_wildcard_deny(self) -> None:
        rules = [make_rule("*", "deny")]
        assert evaluate("bash", rules) == "deny"

    def test_wildcard_deny_then_specific_allow(self) -> None:
        rules = [make_rule("*", "deny"), make_rule("grep", "allow")]
        assert evaluate("grep", rules) == "allow"
        assert evaluate("bash", rules) == "deny"

    def test_last_match_wins(self) -> None:
        rules = [make_rule("bash", "deny"), make_rule("bash", "allow")]
        assert evaluate("bash", rules) == "allow"

    def test_specific_overrides_wildcard(self) -> None:
        rules = [make_rule("*", "allow"), make_rule("task", "deny")]
        assert evaluate("task", rules) == "deny"
        assert evaluate("bash", rules) == "allow"

    def test_no_match_returns_allow(self) -> None:
        rules = [make_rule("bash", "deny")]
        assert evaluate("read", rules) == "allow"


class TestFilterTools:
    def _make_tool(self, name: str) -> object:
        """Create a minimal mock tool with __name__."""

        def fn() -> None:
            pass

        fn.__name__ = name
        return fn

    def test_empty_rules_returns_all(self) -> None:
        tools = [self._make_tool("bash"), self._make_tool("read")]
        assert filter_tools(tools, []) == tools

    def test_deny_wildcard_removes_all(self) -> None:
        tools = [self._make_tool("bash"), self._make_tool("read")]
        rules = [make_rule("*", "deny")]
        assert filter_tools(tools, rules) == []

    def test_deny_specific_removes_only_that_tool(self) -> None:
        bash_tool = self._make_tool("bash")
        read_tool = self._make_tool("read")
        rules = [make_rule("bash", "deny")]
        result = filter_tools([bash_tool, read_tool], rules)
        assert result == [read_tool]

    def test_explore_permission_set(self) -> None:
        """Reproduce the explore agent permission rules."""
        tools = [
            self._make_tool("bash"),
            self._make_tool("grep"),
            self._make_tool("glob_tool"),
            self._make_tool("read"),
            self._make_tool("edit"),
            self._make_tool("write"),
            self._make_tool("task"),
        ]
        rules = [
            make_rule("*", "deny"),
            make_rule("grep", "allow"),
            make_rule("glob_tool", "allow"),
            make_rule("read", "allow"),
            make_rule("bash", "allow"),
        ]
        result = filter_tools(tools, rules)
        names = [t.__name__ for t in result]
        assert sorted(names) == sorted(["bash", "grep", "glob_tool", "read"])

    def test_general_permission_set(self) -> None:
        """Reproduce the general agent permission rules (everything except task)."""
        tools = [
            self._make_tool("bash"),
            self._make_tool("read"),
            self._make_tool("task"),
        ]
        rules = [make_rule("*", "allow"), make_rule("task", "deny")]
        result = filter_tools(tools, rules)
        names = [t.__name__ for t in result]
        assert "task" not in names
        assert "bash" in names
