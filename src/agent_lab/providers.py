"""Provider request/response mapping with an injected transport boundary."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from .contracts import Decision, FinalAnswer, Message, ToolCall, ToolDefinition

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
        pending_call: tuple[str, str] | None = None
        seen_call_ids: set[str] = set()

        for message in messages:
            # 证明发生了调用
            if pending_call is not None:
                pending_call_id, pending_name = pending_call
                if message.role != "tool":
                    raise ProviderMappingError(
                        f"Function call ID {pending_call_id!r} must be immediately "
                        "followed by its tool result"
                    )
                if message.call_id != pending_call_id:
                    raise ProviderMappingError(
                        f"Tool result call ID {message.call_id!r} does not match "
                        f"pending call ID {pending_call_id!r}"
                    )
                if message.name != pending_name:
                    raise ProviderMappingError(
                        f"Tool result for call ID {pending_call_id!r} does not match "
                        f"the pending tool name {pending_name!r}"
                    )

                input_items.append(self._build_function_call_output(message))
                pending_call = None
                continue

            if message.role == "tool":
                raise ProviderMappingError(
                    f"Tool result call ID {message.call_id!r} has no pending "
                    "function call"
                )

            # assistant 开始发起 function call
            if message.role == "assistant" and (
                message.call_id is not None
                or message.name is not None
                or message.arguments is not None
            ):
                # 构建 function call 结构体
                input_items.append(self._build_function_call(message))
                assert isinstance(message.call_id, str)
                assert isinstance(message.name, str)
                if message.call_id in seen_call_ids:
                    raise ProviderMappingError(
                        f"Duplicate function call ID {message.call_id!r}"
                    )
                seen_call_ids.add(message.call_id)
                pending_call = (message.call_id, message.name)
                continue
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

        # 走到这一步代表有没有调用的 function call,因为上一步有的话就会将 pending call 置空
        if pending_call is not None:
            pending_call_id, _ = pending_call
            raise ProviderMappingError(
                f"Function call ID {pending_call_id!r} has no matching tool result"
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

    def _build_function_call(self, message: Message) -> dict[str, Any]:
        if message.role != "assistant":
            raise ProviderMappingError("Function call message role must be assistant")
        if not isinstance(message.call_id, str) or not message.call_id.strip():
            raise ProviderMappingError(
                "Function call message call ID must not be empty"
            )
        if not isinstance(message.name, str) or not message.name.strip():
            raise ProviderMappingError("Function call message name must not be empty")
        if not isinstance(message.arguments, Mapping):
            raise ProviderMappingError(
                "Function call message arguments must be a mapping"
            )
        if message.content != "":
            raise ProviderMappingError("Function call message content must be empty")

        try:
            arguments = json.dumps(
                dict(message.arguments),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ProviderMappingError(
                "Function call message arguments must be JSON serializable"
            ) from error

        return {
            "type": "function_call",
            "call_id": message.call_id,
            "name": ProviderToolNameCodec.encode(message.name),
            "arguments": arguments,
        }

    def _build_function_call_output(self, message: Message) -> dict[str, Any]:
        if message.role != "tool":
            raise ProviderMappingError("Function call output role must be tool")
        if not isinstance(message.call_id, str) or not message.call_id.strip():
            raise ProviderMappingError("Function call output call ID must not be empty")
        if not isinstance(message.name, str) or not message.name.strip():
            raise ProviderMappingError("Function call output name must not be empty")
        if message.arguments is not None:
            raise ProviderMappingError("Function call output arguments must be empty")
        if not isinstance(message.content, str):
            raise ProviderMappingError("Function call output must be text")

        # 这一步主要做校验
        # The Provider output item does not carry the name, but validating it here
        # prevents an invalid local Registry name from entering replay history.
        ProviderToolNameCodec.encode(message.name)

        return {
            "type": "function_call_output",
            "call_id": message.call_id,
            "output": message.content,
        }

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

        if len(output) != 1:
            if any(
                isinstance(item, Mapping) and item.get("type") == "function_call"
                for item in output
            ):
                raise UnsupportedProviderResponseError(
                    "Multiple function calls will be supported in lesson 13"
                )
            raise UnsupportedProviderResponseError(
                "Response output must contain exactly one message"
            )

        message = output[0]
        if isinstance(message, Mapping) and message.get("type") == "function_call":
            return self._parse_function_call(message)
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

    def _parse_function_call(self, item: Mapping[str, Any]) -> ToolCall:
        status = item.get("status")
        if status != "completed":
            raise UnsupportedProviderResponseError(
                f"Response status is {status!r}, not a completed function call"
            )
        call_id = item.get("call_id")
        provider_name = item.get("name")
        if not isinstance(call_id, str) or not call_id.strip():
            raise UnsupportedProviderResponseError(
                "Function call call_id must be a non-empty string"
            )
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise UnsupportedProviderResponseError(
                "Function call name must be a non-empty string"
            )
        try:
            public_name = ProviderToolNameCodec.decode(provider_name)
        except ProviderMappingError as error:
            raise UnsupportedProviderResponseError(
                "Function call contains an invalid Provider tool name"
            ) from error

        arguments = item.get("arguments")
        if not isinstance(arguments, str) or not arguments.strip():
            raise UnsupportedProviderResponseError(
                "Function call arguments must be a non-empty JSON string"
            )
        try:
            parsed_arguments = json.loads(arguments)
        except json.JSONDecodeError as error:
            raise UnsupportedProviderResponseError(
                "Function call arguments must contain valid JSON"
            ) from error
        if not isinstance(parsed_arguments, dict):
            raise UnsupportedProviderResponseError(
                "Function call arguments must decode to a JSON object"
            )

        return ToolCall(
            name=public_name,
            arguments=parsed_arguments,
            call_id=call_id,
        )
