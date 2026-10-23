"""Deterministic test doubles; production code never needs a network for tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .contracts import Decision, Message, ToolDefinition, ToolResult


class ScriptedModel:
    """Return predefined decisions in order and record every model call."""

    def __init__(self, decisions: Iterable[Decision]) -> None:
        self._decisions = deque(decisions)
        self.calls: list[tuple[tuple[Message, ...], tuple[ToolDefinition, ...]]] = []

    def decide(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> Decision:
        self.calls.append((tuple(messages), tuple(tools)))
        if not self._decisions:
            raise AssertionError("ScriptedModel ran out of decisions")
        return self._decisions.popleft()


class RecordingTool:
    """A tiny tool that records arguments and returns a fixed observation."""

    def __init__(
        self,
        name: str,
        result: str | ToolResult,
        description: str = "test tool",
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.result = (
            result if isinstance(result, ToolResult) else ToolResult.success(result)
        )
        self.calls: list[dict[str, Any]] = []
        self.parameters = (
            parameters
            if parameters is not None
            else {
                "type": "object",
                "additionalProperties": True,
            }
        )

    def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        return self.result


class ScriptedTool:
    """Return predefined tool results in order and record every call."""

    def __init__(
        self,
        name: str,
        results: Iterable[ToolResult],
        description: str = "test tool",
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self._results = deque(results)
        self.calls: list[dict[str, Any]] = []
        self.parameters = (
            parameters
            if parameters is not None
            else {
                "type": "object",
                "additionalProperties": True,
            }
        )

    def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        self.calls.append(dict(arguments))
        if not self._results:
            raise AssertionError("ScriptedTool ran out of results")
        return self._results.popleft()
