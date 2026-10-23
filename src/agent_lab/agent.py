"""The control loop for a minimal tool-using agent."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .contracts import (
    CancellationToken,
    FinalAnswer,
    Message,
    Model,
    RetryPolicy,
    RunResult,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolErrorKind,
    ToolResult,
)

type Deadline = float | None


class UnknownToolError(LookupError):
    """Raised when a model asks for a tool that the host did not provide."""


class StepLimitExceeded(RuntimeError):
    """Raised when an agent does not finish inside its execution budget."""


class AgentTimeoutError(TimeoutError):
    """Raised when the cooperative run deadline is exhausted."""


class AgentCancelledError(RuntimeError):
    """Raised when a caller requests cooperative cancellation."""


class InvalidToolSchemaError(ValueError):
    """Raised when a tool declares an invalid JSON Schema."""


def _format_tool_result(result: ToolResult) -> str:
    if result.error is not None:
        return f"Tool error [{result.error.kind.value}]: {result.error.message}"

    assert result.output is not None
    return result.output


class Agent:
    def __init__(
        self,
        model: Model,
        tools: Iterable[Tool] = (),
        *,
        max_steps: int = 8,
        retry_policy: RetryPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        self._tools: dict[str, tuple[Tool, Draft202012Validator]] = {}
        for tool in tools:
            try:
                Draft202012Validator.check_schema(tool.parameters)
                validator = Draft202012Validator(tool.parameters)
                self._tools[tool.name] = (
                    tool,
                    validator,
                )
            except SchemaError as e:
                raise InvalidToolSchemaError(
                    f"tool {tool.name} schema error: {e.message}"
                ) from e

        self._model = model
        self._max_steps = max_steps
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._clock = clock
        self._sleep = sleep

    def run(
        self,
        question: str,
        *,
        timeout: float | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> RunResult:
        """Run until the model answers or a control boundary stops execution."""
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must not be negative")

        deadline = None if timeout is None else self._clock() + timeout
        self._raise_if_stopped(deadline, cancellation_token)

        history: list[Message] = [Message(role="user", content=question)]
        tools = tuple(
            ToolDefinition(
                name=tool.name, description=tool.description, parameters=tool.parameters
            )
            for tool, _ in self._tools.values()
        )
        for step in range(self._max_steps):
            self._raise_if_stopped(deadline, cancellation_token)
            decision = self._model.decide(history, tools)
            self._raise_if_stopped(deadline, cancellation_token)

            if isinstance(decision, FinalAnswer):
                history.append(Message(role="assistant", content=decision.content))
                return RunResult(
                    answer=decision.content,
                    steps=step + 1,
                    messages=tuple(history),
                )
            if isinstance(decision, ToolCall):
                tool_entry = self._tools.get(decision.name)
                if tool_entry is None:
                    raise UnknownToolError(
                        f"Model requested unknown tool: {decision.name}"
                    )
                tool, validator = tool_entry
                try:
                    validator.validate(dict(decision.arguments))
                except ValidationError as e:
                    self._raise_if_stopped(deadline, cancellation_token)
                    tool_result = ToolResult.failure(
                        ToolErrorKind.INVALID_ARGUMENTS,
                        e.message,
                    )
                else:
                    tool_result = self._run_tool_with_retries(
                        tool,
                        decision.arguments,
                        deadline,
                        cancellation_token,
                    )

                history.append(
                    Message(
                        role="tool",
                        content=_format_tool_result(tool_result),
                        name=tool.name,
                    )
                )

        raise StepLimitExceeded("Step limit exceeded")

    def _run_tool_with_retries(
        self,
        tool: Tool,
        arguments: Mapping[str, object],
        deadline: Deadline,
        cancellation_token: CancellationToken | None,
    ) -> ToolResult:
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            self._raise_if_stopped(deadline, cancellation_token)
            result = tool.run(arguments)
            self._raise_if_stopped(deadline, cancellation_token)

            if result.error is None or not result.error.retryable:
                return result
            if attempt == self._retry_policy.max_attempts:
                return result

            delay = self._retry_policy.delay_after(attempt)
            self._raise_if_stopped(deadline, cancellation_token)
            if deadline is not None and delay >= deadline - self._clock():
                raise AgentTimeoutError("agent run timed out during retry backoff")

            self._sleep(delay)
            self._raise_if_stopped(deadline, cancellation_token)

        raise AssertionError("retry loop exhausted without returning a result")

    def _raise_if_stopped(
        self,
        deadline: Deadline,
        cancellation_token: CancellationToken | None,
    ) -> None:
        if cancellation_token is not None and cancellation_token.is_cancelled:
            raise AgentCancelledError("agent run was cancelled")
        if deadline is not None and self._clock() >= deadline:
            raise AgentTimeoutError("agent run timed out")
