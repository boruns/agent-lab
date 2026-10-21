"""Small, provider-neutral contracts used by the agent loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, Self

type Role = Literal["user", "assistant", "tool"]


class ToolErrorKind(StrEnum):
    """Stable categories for expected tool-call failures."""

    INVALID_ARGUMENTS = "invalid_arguments"
    EXECUTION_ERROR = "execution_error"


@dataclass(frozen=True)
class ToolError:
    kind: ToolErrorKind
    message: str


@dataclass(frozen=True)
class ToolResult:
    """Exactly one of ``output`` or ``error`` from a tool execution."""

    output: str | None = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if (self.output is None) == (self.error is None):
            raise ValueError("ToolResult must contain exactly one of output or error")

    @classmethod
    def success(cls, output: str) -> Self:
        return cls(output=output)

    @classmethod
    def failure(cls, kind: ToolErrorKind, message: str) -> Self:
        return cls(error=ToolError(kind=kind, message=message))

    @property
    def is_success(self) -> bool:
        return self.error is None


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

    def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        """Execute the tool and return a structured expected outcome."""


@dataclass(frozen=True)
class RunResult:
    answer: str
    steps: int
    messages: tuple[Message, ...]
