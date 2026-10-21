"""Small, provider-neutral contracts used by the agent loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

type Role = Literal["user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    name: str | None = None


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class FinalAnswer:
    content: str


type Decision = ToolCall | FinalAnswer


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, Any]


class Model(Protocol):
    def decide(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> Decision:
        """Choose a tool call or return a final answer."""


class Tool(Protocol):
    name: str
    description: str
    parameters: Mapping[str, Any]

    def run(self, arguments: Mapping[str, Any]) -> str:
        """Execute the tool and return an observation for the model."""


@dataclass(frozen=True)
class RunResult:
    answer: str
    steps: int
    messages: tuple[Message, ...]
