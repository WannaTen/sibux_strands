"""Custom LiteLLMModel that preserves reasoning_content for Kimi k2.5."""

from typing import Any

from ..types.content import ContentBlock, Messages, SystemContentBlock
from .litellm import LiteLLMModel


class MoonshotKimiModel(LiteLLMModel):
    """Custom model for Moonshot Kimi that preserves reasoning_content in multi-turn conversations.

    Kimi k2.5 requires reasoning_content to be passed back in subsequent tool calls.
    The default LiteLLMModel/OpenAIModel filters out reasoningContent blocks.
    """

    @classmethod
    def _format_regular_messages(cls, messages: Messages, **kwargs: Any) -> list[dict[str, Any]]:
        """Format messages while preserving reasoningContent for assistant messages.

        This overrides the parent method to keep reasoningContent blocks instead of
        filtering them out.
        """
        formatted_messages = []

        for message in messages:
            contents = message["content"]
            role = message["role"]

            # Separate different content types
            normal_contents: list[ContentBlock] = []
            reasoning_contents: list[ContentBlock] = []
            tool_use_contents: list[ContentBlock] = []
            tool_result_contents: list[ContentBlock] = []

            for content in contents:
                if "reasoningContent" in content:
                    reasoning_contents.append(content)
                elif "toolUse" in content:
                    tool_use_contents.append(content)
                elif "toolResult" in content:
                    tool_result_contents.append(content)
                else:
                    normal_contents.append(content)

            # Format normal contents (text, image, etc.)
            formatted_contents = [cls.format_request_message_content(content) for content in normal_contents]

            # Format tool calls
            formatted_tool_calls = [
                cls.format_request_message_tool_call(content["toolUse"]) for content in tool_use_contents
            ]

            # Format tool results
            formatted_tool_messages = [
                cls.format_request_tool_message(content["toolResult"]) for content in tool_result_contents
            ]

            # Build the main message
            formatted_message: dict[str, Any] = {
                "role": role,
                "content": formatted_contents,
            }

            # Add tool_calls if present
            if formatted_tool_calls:
                formatted_message["tool_calls"] = formatted_tool_calls

            # For assistant messages with reasoningContent, we need to preserve it
            # Moonshot API expects reasoning_content as a string at the message level
            if role == "assistant" and reasoning_contents:
                # Concatenate all reasoning text
                reasoning_text_parts = []
                for rc in reasoning_contents:
                    if "reasoningContent" in rc and "reasoningText" in rc["reasoningContent"]:
                        text = rc["reasoningContent"]["reasoningText"].get("text", "")
                        if text:
                            reasoning_text_parts.append(text)

                if reasoning_text_parts:
                    # Moonshot API expects reasoning_content as a string field on the message
                    formatted_message["reasoning_content"] = "\n".join(reasoning_text_parts)

            formatted_messages.append(formatted_message)

            # Add tool result messages
            for tool_msg in formatted_tool_messages:
                formatted_messages.append(tool_msg)

        return formatted_messages

    @classmethod
    def format_request_messages(
        cls,
        messages: Messages,
        system_prompt: str | None = None,
        *,
        system_prompt_content: list[SystemContentBlock] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Format messages for Moonshot API with reasoning_content support."""
        formatted_messages = cls._format_system_messages(system_prompt, system_prompt_content=system_prompt_content)
        formatted_messages.extend(cls._format_regular_messages(messages))

        # Filter out empty messages but keep those with tool_calls or reasoning_content
        return [
            message
            for message in formatted_messages
            if message.get("content") or message.get("tool_calls") or message.get("reasoning_content")
        ]
