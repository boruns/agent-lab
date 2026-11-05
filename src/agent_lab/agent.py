"""The control loop for a minimal tool-using agent."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import TracebackType
from typing import Self
from uuid import uuid4

from jsonschema.exceptions import ValidationError

from .contracts import (
    CancellationToken,
    FinalAnswer,
    Message,
    Model,
    RetryPolicy,
    RunResult,
    Tool,
    ToolCall,
    ToolCallBatch,
    ToolConfirmationRequest,
    ToolErrorKind,
    ToolExecutionContext,
    ToolPermission,
    ToolResult,
)
from .registry import RegisteredTool, ToolRegistry, ToolSource

type Deadline = float | None


@dataclass
class _PreparedToolCall:
    """Host-owned state prepared before any call in a batch executes."""

    call: ToolCall
    registered: RegisteredTool
    result: ToolResult | None = None
    idempotency_key: str | None = None


class UnknownToolError(LookupError):
    """Raised when a model asks for a tool that the host did not provide."""


class StepLimitExceeded(RuntimeError):
    """Raised when an agent does not finish inside its execution budget."""


class AgentTimeoutError(TimeoutError):
    """Raised when the cooperative run deadline is exhausted."""


class AgentCancelledError(RuntimeError):
    """Raised when a caller requests cooperative cancellation."""


class ToolPermissionDeniedError(PermissionError):
    """Raised when the host did not grant a tool's permission class."""


class ToolConfirmationRequiredError(PermissionError):
    """Raised when a write call has no confirmation handler."""


class ToolConfirmationRejectedError(PermissionError):
    """Raised when a write call is explicitly rejected."""


def _format_tool_result(result: ToolResult) -> str:
    if result.error is not None:
        return f"Tool error [{result.error.kind.value}]: {result.error.message}"

    assert result.output is not None
    return result.output


class Agent:
    def __init__(
        self,
        model: Model,
        tools: Iterable[ToolSource] = (),
        *,
        max_steps: int = 8,
        retry_policy: RetryPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        allowed_permissions: Iterable[ToolPermission] = (ToolPermission.READ,),
        confirmation_handler: Callable[[ToolConfirmationRequest], bool] | None = None,
        idempotency_key_factory: Callable[[], str] = lambda: uuid4().hex,
        parallel_tool_calls: bool = False,
        max_parallel_tools: int = 4,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_parallel_tools < 1:
            raise ValueError("max_parallel_tools must be at least 1")

        self._tool_registry = ToolRegistry(tools=tools)
        self._tool_registry.start()
        self._model = model
        self._max_steps = max_steps
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy()
        self._clock = clock
        self._sleep = sleep
        self._allowed_permissions = frozenset(allowed_permissions)
        self._confirmation_handler = confirmation_handler
        self._idempotency_key_factory = idempotency_key_factory
        self._parallel_tool_calls = parallel_tool_calls
        self._max_parallel_tools = max_parallel_tools

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

        # agent 最多循环次数
        for step in range(self._max_steps):
            self._raise_if_stopped(deadline, cancellation_token)
            decision = self._model.decide(history, self._tool_registry.definitions())
            self._raise_if_stopped(deadline, cancellation_token)

            # 如果已经完成了任务，直接返回
            if isinstance(decision, FinalAnswer):
                history.append(Message(role="assistant", content=decision.content))
                return RunResult(
                    answer=decision.content,
                    steps=step + 1,
                    messages=tuple(history),
                )
            if isinstance(decision, ToolCallBatch):
                self._execute_tool_call_batch(
                    history,
                    decision,
                    deadline,
                    cancellation_token,
                )
                continue
            # 如果需要调用 Tool ，则开始执行 ToolCall
            if isinstance(decision, ToolCall):
                registerd = self._tool_registry.resolve(decision.name)
                if registerd is None:
                    raise UnknownToolError(
                        f"Model requested unknown tool: {decision.name}"
                    )

                # 判断 tool 的权限是否在授权集合中
                if registerd.tool.permission not in self._allowed_permissions:
                    raise ToolPermissionDeniedError(
                        f"Tool: {registerd.public_name} {registerd.tool.permission} permission not allow "
                    )

                try:
                    registerd.validator.validate(dict(decision.arguments))
                except ValidationError as e:
                    self._raise_if_stopped(deadline, cancellation_token)
                    tool_result = ToolResult.failure(
                        ToolErrorKind.INVALID_ARGUMENTS,
                        e.message,
                    )
                else:
                    idempotency_key = None
                    if registerd.tool.permission is ToolPermission.WRITE:
                        if self._confirmation_handler is None:
                            raise ToolConfirmationRequiredError(
                                f"Tool: {registerd.public_name} permission is write, confirmation handler is none"
                            )
                        idempotency_key = self._idempotency_key_factory()
                        if not self._confirmation_handler(
                            ToolConfirmationRequest(
                                registerd.public_name,
                                dict(decision.arguments),
                                idempotency_key,
                            )
                        ):
                            raise ToolConfirmationRejectedError(
                                f"Tool: {registerd.public_name} confirmation hand is rejected"
                            )

                    tool_result = self._run_tool_with_retries(
                        registerd.tool,
                        decision.arguments,
                        deadline,
                        cancellation_token,
                        idempotency_key,
                    )

                # 如果调用 Tool 的时候 call_id 为空，有可能是工具调用失败或者参数校验失败
                if decision.call_id is None:
                    history.append(
                        Message(
                            role="tool",
                            content=_format_tool_result(tool_result),
                            name=registerd.public_name,
                        )
                    )
                else:
                    self._append_function_call_exchange(
                        history,
                        decision,
                        registerd.public_name,
                        tool_result,
                    )

        raise StepLimitExceeded("Step limit exceeded")

    def _execute_tool_call_batch(
        self,
        history: list[Message],
        decision: ToolCallBatch,
        deadline: Deadline,
        cancellation_token: CancellationToken | None,
    ) -> None:
        """Preflight, execute, and record one ordered tool-call batch."""
        self._raise_if_stopped(deadline, cancellation_token)

        seen_call_ids: set[str] = set()
        for call in decision.calls:
            self._raise_if_stopped(deadline, cancellation_token)
            call_id = call.call_id
            if not isinstance(call_id, str) or not call_id.strip():
                raise ValueError("Tool call ID must be a non-empty string")
            if call_id in seen_call_ids:
                raise ValueError(f"Duplicate tool call ID {call_id!r}")
            seen_call_ids.add(call_id)

        prepared_calls: list[_PreparedToolCall] = []
        for call in decision.calls:
            self._raise_if_stopped(deadline, cancellation_token)
            registered = self._tool_registry.resolve(call.name)
            if registered is None:
                raise UnknownToolError(f"Model requested unknown tool: {call.name}")
            prepared_calls.append(_PreparedToolCall(call, registered))

        for prepared in prepared_calls:
            self._raise_if_stopped(deadline, cancellation_token)
            registered = prepared.registered
            if registered.tool.permission not in self._allowed_permissions:
                raise ToolPermissionDeniedError(
                    f"Tool: {registered.public_name} "
                    f"{registered.tool.permission} permission not allow"
                )

        for prepared in prepared_calls:
            self._raise_if_stopped(deadline, cancellation_token)
            try:
                prepared.registered.validator.validate(dict(prepared.call.arguments))
            except ValidationError as error:
                prepared.result = ToolResult.failure(
                    ToolErrorKind.INVALID_ARGUMENTS,
                    error.message,
                )

        for prepared in prepared_calls:
            self._raise_if_stopped(deadline, cancellation_token)
            registered = prepared.registered
            if (
                prepared.result is not None
                or registered.tool.permission is not ToolPermission.WRITE
            ):
                continue
            if self._confirmation_handler is None:
                raise ToolConfirmationRequiredError(
                    f"Tool: {registered.public_name} permission is write, "
                    "confirmation handler is none"
                )

            prepared.idempotency_key = self._idempotency_key_factory()
            if not self._confirmation_handler(
                ToolConfirmationRequest(
                    registered.public_name,
                    dict(prepared.call.arguments),
                    prepared.idempotency_key,
                )
            ):
                raise ToolConfirmationRejectedError(
                    f"Tool: {registered.public_name} confirmation handler rejected"
                )

        self._raise_if_stopped(deadline, cancellation_token)
        should_run_in_parallel = self._parallel_tool_calls and all(
            prepared.registered.tool.permission is ToolPermission.READ
            for prepared in prepared_calls
        )
        if should_run_in_parallel:
            self._execute_prepared_calls_in_parallel(
                prepared_calls,
                deadline,
                cancellation_token,
            )
        else:
            self._execute_prepared_calls_sequentially(
                prepared_calls,
                deadline,
                cancellation_token,
            )

        self._raise_if_stopped(deadline, cancellation_token)
        for prepared in prepared_calls:
            call = prepared.call
            assert isinstance(call.call_id, str)
            history.append(
                Message(
                    role="assistant",
                    content="",
                    name=prepared.registered.public_name,
                    call_id=call.call_id,
                    arguments=dict(call.arguments),
                )
            )

        for prepared in prepared_calls:
            call = prepared.call
            result = prepared.result
            assert isinstance(call.call_id, str)
            assert result is not None
            history.append(
                Message(
                    role="tool",
                    content=_format_tool_result(result),
                    name=prepared.registered.public_name,
                    call_id=call.call_id,
                )
            )

    def _execute_prepared_calls_sequentially(
        self,
        prepared_calls: list[_PreparedToolCall],
        deadline: Deadline,
        cancellation_token: CancellationToken | None,
    ) -> None:
        for prepared in prepared_calls:
            self._raise_if_stopped(deadline, cancellation_token)
            if prepared.result is not None:
                continue
            prepared.result = self._run_tool_with_retries(
                prepared.registered.tool,
                prepared.call.arguments,
                deadline,
                cancellation_token,
                prepared.idempotency_key,
            )

    def _execute_prepared_calls_in_parallel(
        self,
        prepared_calls: list[_PreparedToolCall],
        deadline: Deadline,
        cancellation_token: CancellationToken | None,
    ) -> None:
        pending_calls = [
            prepared for prepared in prepared_calls if prepared.result is None
        ]
        if not pending_calls:
            return

        max_workers = min(self._max_parallel_tools, len(pending_calls))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for prepared in pending_calls:
                self._raise_if_stopped(deadline, cancellation_token)
                futures.append(
                    (
                        prepared,
                        executor.submit(
                            self._run_tool_with_retries,
                            prepared.registered.tool,
                            prepared.call.arguments,
                            deadline,
                            cancellation_token,
                            prepared.idempotency_key,
                        ),
                    )
                )

            for prepared, future in futures:
                prepared.result = future.result()
                self._raise_if_stopped(deadline, cancellation_token)

    def _append_function_call_exchange(
        self,
        history: list[Message],
        decision: ToolCall,
        public_name: str,
        result: ToolResult,
    ) -> None:
        if not isinstance(decision.call_id, str) or not decision.call_id.strip():
            raise UnknownToolError(f"Tool {decision.name} call id must be not empty")

        history.append(
            Message(
                role="assistant",
                content="",
                name=public_name,
                call_id=decision.call_id,
                arguments=dict(decision.arguments),
            )
        )
        history.append(
            Message(
                role="tool",
                content=_format_tool_result(result),
                name=public_name,
                call_id=decision.call_id,
            )
        )

    def _run_tool_with_retries(
        self,
        tool: Tool,
        arguments: Mapping[str, object],
        deadline: Deadline,
        cancellation_token: CancellationToken | None,
        idempotency_key: str | None,
    ) -> ToolResult:
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            self._raise_if_stopped(deadline, cancellation_token)
            context = ToolExecutionContext(
                attempt=attempt,
                idempotency_key=idempotency_key,
            )
            result = tool.run(arguments, context=context)
            self._raise_if_stopped(deadline, cancellation_token)

            if result.error is None or not result.error.retryable:
                return result
            if attempt == self._retry_policy.max_attempts:
                return result

            if (
                tool.permission is ToolPermission.WRITE
                and not tool.supports_idempotency
            ):
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

    def close(self) -> None:
        self._tool_registry.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()
