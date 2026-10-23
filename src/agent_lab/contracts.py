"""Small, provider-neutral contracts used by the agent loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from threading import Event
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
    retryable: bool = False


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
    def failure(
        cls,
        kind: ToolErrorKind,
        message: str,
        *,
        retryable: bool = False,
    ) -> Self:
        return cls(error=ToolError(kind=kind, message=message, retryable=retryable))

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff for one tool call."""

    max_attempts: int = 3
    initial_delay: float = 0.1
    backoff_multiplier: float = 2.0
    max_delay: float = 5.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_delay < 0:
            raise ValueError("initial_delay must not be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if self.max_delay < 0:
            raise ValueError("max_delay must not be negative")

    def delay_after(self, failed_attempt: int) -> float:
        if failed_attempt < 1:
            raise ValueError("failed_attempt must be at least 1")
        delay = self.initial_delay * self.backoff_multiplier ** (failed_attempt - 1)
        return min(delay, self.max_delay)


class CancellationToken:
    """Thread-safe cooperative cancellation signal."""

    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()


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
