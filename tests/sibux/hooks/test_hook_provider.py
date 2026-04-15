"""Tests for Sibux hook providers."""

from pathlib import Path
from unittest.mock import patch

from sibux.agent.agent_factory import create
from sibux.config.config import Config
from sibux.config.defaults import default_config_dict
from sibux.hooks import SibuxHookProvider
from strands.hooks import AfterToolCallEvent, BeforeInvocationEvent, BeforeToolCallEvent, HookProvider
from tests.fixtures.mocked_model_provider import MockedModelProvider


class RecordingToolHookProvider(SibuxHookProvider):
    """Capture tool lifecycle events for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.before_tool_events = []
        self.after_tool_events = []

    def on_before_tool_call(self, event: BeforeToolCallEvent) -> None:
        self.before_tool_events.append(event)

    def on_after_tool_call(self, event: AfterToolCallEvent) -> None:
        self.after_tool_events.append(event)


class MessageRewriteHookProvider(SibuxHookProvider):
    """Rewrite invocation messages before model execution."""

    def __init__(self, rewritten_text: str) -> None:
        super().__init__()
        self.rewritten_text = rewritten_text

    def on_before_invocation(self, event: BeforeInvocationEvent) -> None:
        if event.messages is None:
            return
        event.messages = [{"role": "user", "content": [{"text": self.rewritten_text}]}]


def test_sibux_hook_provider_implements_strands_protocol() -> None:
    provider = SibuxHookProvider()
    assert isinstance(provider, HookProvider)


def test_sibux_hook_provider_receives_tool_events(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello\n", encoding="utf-8")

    config = Config.model_validate(default_config_dict())
    agent_config = config.agents["build"]
    provider = RecordingToolHookProvider()

    with patch("sibux.agent.agent_factory._resolve_model", return_value=MockedModelProvider([])):
        agent = create(config, agent_config, hooks=[provider])

    result = agent.tool.read(file_path=str(sample_file))

    assert result["status"] == "success"
    assert len(provider.before_tool_events) == 1
    assert provider.before_tool_events[0].tool_use["name"] == "read"
    assert len(provider.after_tool_events) == 1
    assert provider.after_tool_events[0].tool_use["name"] == "read"
    assert provider.after_tool_events[0].result["status"] == "success"


def test_sibux_hook_provider_can_modify_invocation_messages(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    config = Config.model_validate(default_config_dict())
    agent_config = config.agents["build"]
    provider = MessageRewriteHookProvider("rewritten by hook")
    model = MockedModelProvider([{"role": "assistant", "content": [{"text": "ok"}]}])

    with patch("sibux.agent.agent_factory._resolve_model", return_value=model):
        agent = create(config, agent_config, hooks=[provider])

    agent("original input")

    assert agent.messages[0]["role"] == "user"
    assert agent.messages[0]["content"][0]["text"] == "rewritten by hook"
