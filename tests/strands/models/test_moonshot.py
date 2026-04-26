import importlib

import pytest

pytest.importorskip("litellm.exceptions")
MoonshotKimiModel = importlib.import_module("strands.models.moonshot").MoonshotKimiModel


def test_format_regular_messages_preserves_assistant_reasoning_content():
    messages = [
        {
            "role": "assistant",
            "content": [
                {"text": "I can help with that."},
                {"reasoningContent": {"reasoningText": {"text": "first thought", "signature": "sig-1"}}},
                {"reasoningContent": {"reasoningText": {"text": "second thought", "signature": "sig-2"}}},
                {
                    "toolUse": {
                        "input": {"query": "moonshot"},
                        "name": "search",
                        "toolUseId": "tool-1",
                    },
                },
            ],
        }
    ]

    tru_result = MoonshotKimiModel._format_regular_messages(messages)

    exp_result = [
        {
            "role": "assistant",
            "content": [{"text": "I can help with that.", "type": "text"}],
            "tool_calls": [
                {
                    "function": {"arguments": '{"query": "moonshot"}', "name": "search"},
                    "id": "tool-1",
                    "type": "function",
                }
            ],
            "reasoning_content": "first thought\nsecond thought",
        }
    ]
    assert tru_result == exp_result


def test_format_regular_messages_does_not_preserve_non_assistant_reasoning_content():
    messages = [
        {
            "role": "user",
            "content": [
                {"text": "Hello"},
                {"reasoningContent": {"reasoningText": {"text": "hidden", "signature": "sig"}}},
            ],
        }
    ]

    tru_result = MoonshotKimiModel._format_regular_messages(messages)

    exp_result = [{"role": "user", "content": [{"text": "Hello", "type": "text"}]}]
    assert tru_result == exp_result


def test_format_request_messages_keeps_reasoning_only_assistant_message():
    messages = [
        {
            "role": "assistant",
            "content": [{"reasoningContent": {"reasoningText": {"text": "tool reasoning", "signature": "sig"}}}],
        }
    ]

    tru_result = MoonshotKimiModel.format_request_messages(messages)

    exp_result = [{"role": "assistant", "content": [], "reasoning_content": "tool reasoning"}]
    assert tru_result == exp_result


def test_format_request_messages_filters_empty_non_reasoning_messages():
    messages = [
        {"role": "user", "content": []},
        {
            "role": "assistant",
            "content": [
                {
                    "toolUse": {
                        "input": {"expression": "2+2"},
                        "name": "calculator",
                        "toolUseId": "calc-1",
                    },
                }
            ],
        },
    ]

    tru_result = MoonshotKimiModel.format_request_messages(messages)

    exp_result = [
        {
            "role": "assistant",
            "content": [],
            "tool_calls": [
                {
                    "function": {"arguments": '{"expression": "2+2"}', "name": "calculator"},
                    "id": "calc-1",
                    "type": "function",
                }
            ],
        }
    ]
    assert tru_result == exp_result


def test_format_request_messages_keeps_litellm_system_cache_format():
    messages = [{"role": "user", "content": [{"text": "Hello"}]}]
    system_prompt_content = [{"text": "You are helpful."}, {"cachePoint": {"type": "default"}}]

    tru_result = MoonshotKimiModel.format_request_messages(messages, system_prompt_content=system_prompt_content)

    exp_result = [
        {
            "role": "system",
            "content": [{"type": "text", "text": "You are helpful.", "cache_control": {"type": "ephemeral"}}],
        },
        {"role": "user", "content": [{"text": "Hello", "type": "text"}]},
    ]
    assert tru_result == exp_result
