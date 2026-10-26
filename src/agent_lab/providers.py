"""Provider request/response mapping with an injected transport boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .contracts import Decision, FinalAnswer, Message, ToolDefinition

_PUBLIC_TOOL_NAME_PATTERN = re.compile(
    r"[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)?\Z"
)
_PROVIDER_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class ProviderMappingError(ValueError):
    """Raised when a project value cannot be represented by a provider."""


class UnsupportedProviderResponseError(RuntimeError):
    """Raised when a response needs a capability from a later lesson."""


class ProviderTransport(Protocol):
    """Minimal synchronous JSON transport injected into an adapter."""

    def create_response(
        self,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Send one provider request and return the decoded JSON object."""
        ...


class ProviderToolNameCodec:
    """Reversibly map registry public names to provider-safe names."""

    @classmethod
    def encode(cls, public_name: str) -> str:
        if _PUBLIC_TOOL_NAME_PATTERN.fullmatch(public_name) is None:
            raise ProviderMappingError(
                f"Invalid registry public tool name: {public_name!r}"
            )

        provider_name = public_name.replace("_", "_u").replace(".", "_d")
        if len(provider_name) > 128:
            raise ProviderMappingError(
                "Encoded provider tool name exceeds the 128 character limit"
            )
        if _PROVIDER_TOOL_NAME_PATTERN.fullmatch(provider_name) is None:
            raise ProviderMappingError(
                f"Invalid encoded provider tool name: {provider_name!r}"
            )
        return provider_name

    @classmethod
    def decode(cls, provider_name: str) -> str:
        if len(provider_name) > 128:
            raise ProviderMappingError(
                "Provider tool name exceeds the 128 character limit"
            )
        if _PROVIDER_TOOL_NAME_PATTERN.fullmatch(provider_name) is None:
            raise ProviderMappingError(f"Invalid provider tool name: {provider_name!r}")

        decoded: list[str] = []
        index = 0
        while index < len(provider_name):
            character = provider_name[index]
            if character != "_":
                decoded.append(character)
                index += 1
                continue

            if index + 1 >= len(provider_name):
                raise ProviderMappingError("Incomplete provider tool name escape")

            escape = provider_name[index + 1]
            if escape == "u":
                decoded.append("_")
            elif escape == "d":
                decoded.append(".")
            else:
                raise ProviderMappingError(
                    f"Unknown provider tool name escape: _{escape}"
                )
            index += 2

        public_name = "".join(decoded)
        if _PUBLIC_TOOL_NAME_PATTERN.fullmatch(public_name) is None:
            raise ProviderMappingError(
                f"Decoded registry public tool name is invalid: {public_name!r}"
            )
        return public_name


class DeepSeekResponsesAdapter:
    """Map project contracts to the DeepSeek Responses API JSON shape."""

    def __init__(self, model: str, transport: ProviderTransport) -> None:
        if not model:
            raise ValueError("model must not be empty")
        self._model = model
        self._transport = transport

    def decide(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> Decision:
        payload = self.build_request(messages, tools)
        response = self._transport.create_response(payload)
        return self.parse_response(response)

    def build_request(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> dict[str, Any]:
        """Build one non-streaming, non-thinking Responses API request."""
        input_items: list[dict[str, Any]] = []
        for message in messages:
            if message.role == "tool":
                raise ProviderMappingError("Tool message call ID is missing")
            if message.role not in ("user", "assistant"):
                raise ProviderMappingError(
                    f"Unsupported project message role: {message.role!r}"
                )
            input_items.append(
                {
                    "type": "message",
                    "role": message.role,
                    "content": message.content,
                }
            )

        request: dict[str, Any] = {
            "model": self._model,
            "input": input_items,
            "reasoning": {"effort": "none"},
            "stream": False,
        }
        if tools:
            request["tools"] = [
                {
                    "type": "function",
                    "name": ProviderToolNameCodec.encode(tool.name),
                    "description": tool.description,
                    "parameters": dict(tool.parameters),
                }
                for tool in tools
            ]
        return request

    def parse_response(self, response: Mapping[str, Any]) -> Decision:
        """Parse the lesson-10 subset: one completed text response."""
        status = response.get("status")
        if status != "completed":
            raise UnsupportedProviderResponseError(
                f"Response status is {status!r}, not a completed answer"
            )

        output = response.get("output")
        if not isinstance(output, list):
            raise UnsupportedProviderResponseError("Response output must be a list")

        for item in output:
            if isinstance(item, Mapping) and item.get("type") == "function_call":
                raise UnsupportedProviderResponseError(
                    "Function calls will be supported in lesson 12"
                )

        if len(output) != 1:
            raise UnsupportedProviderResponseError(
                "Response output must contain exactly one message"
            )

        message = output[0]
        if not isinstance(message, Mapping) or message.get("type") != "message":
            raise UnsupportedProviderResponseError(
                "Response output item must be a message"
            )
        if message.get("role") != "assistant":
            raise UnsupportedProviderResponseError(
                "Response message role must be assistant"
            )
        if message.get("status") != "completed":
            raise UnsupportedProviderResponseError(
                "Response message status must be completed"
            )

        content = message.get("content")
        if not isinstance(content, list):
            raise UnsupportedProviderResponseError(
                "Response message content must be a list"
            )

        output_texts: list[str] = []
        for content_part in content:
            if (
                not isinstance(content_part, Mapping)
                or content_part.get("type") != "output_text"
            ):
                raise UnsupportedProviderResponseError(
                    "Response message contains an unsupported content part"
                )
            text = content_part.get("text")
            if not isinstance(text, str):
                raise UnsupportedProviderResponseError(
                    "Response output_text must contain text"
                )
            if text:
                output_texts.append(text)

        if not output_texts:
            raise UnsupportedProviderResponseError(
                "Response message contains no output text"
            )
        return FinalAnswer("".join(output_texts))
