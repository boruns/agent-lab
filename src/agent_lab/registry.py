"""Tool discovery, naming, validation, and lifecycle ownership."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from jsonschema import Draft202012Validator, SchemaError

from .contracts import ManagedTool, Tool, ToolDefinition


class DuplicateToolError(ValueError):
    """Raised when two tools claim the same public name."""


class InvalidToolNameError(ValueError):
    """Raised when a local name or namespace is not a valid name segment."""


class InvalidToolSchemaError(ValueError):
    """Raised when a tool declares an invalid JSON Schema."""


class ToolRegistryStateError(RuntimeError):
    """Raised when an operation is invalid for the registry's current state."""


class ToolRegistryState(StrEnum):
    OPEN = "open"
    STARTED = "started"
    CLOSED = "closed"


@dataclass(frozen=True)
class ToolRegistration:
    """Place a tool in an optional host-owned namespace."""

    tool: Tool
    namespace: str | None = None


@dataclass(frozen=True)
class RegisteredTool:
    """An immutable lookup entry prepared by the registry."""

    public_name: str
    tool: Tool
    validator: Draft202012Validator

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.public_name,
            description=self.tool.description,
            parameters=self.tool.parameters,
        )


type ToolSource = Tool | ToolRegistration


class ToolRegistry:
    """Own a stable, validated set of tools for one Agent.

    This is the lesson 8 exercise. Implement the state transitions and methods
    described in ``docs/02-tools/08-tool-registry.md``.
    """

    PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

    def __init__(self, tools: Iterable[ToolSource] = ()) -> None:
        self._state = ToolRegistryState.OPEN
        self._entries: dict[str, RegisteredTool] = {}
        self._started_tools: list[ManagedTool] = []

        for source in tools:
            if isinstance(source, ToolRegistration):
                self.register(source.tool, namespace=source.namespace)
            else:
                self.register(source)

    @property
    def state(self) -> ToolRegistryState:
        return self._state

    def register(self, tool: Tool, *, namespace: str | None = None) -> str:
        # 只能在 OPEN 状态下调用
        if self.state is not ToolRegistryState.OPEN:
            raise ToolRegistryStateError("Register state is not open now")

        # validate tool name
        if self.PATTERN.fullmatch(tool.name) is None:
            raise InvalidToolNameError(f"Tool {tool.name} name is invalidate")

        # validate namespace
        if namespace is not None and self.PATTERN.fullmatch(namespace) is None:
            raise InvalidToolNameError("Register namespace is invalidate")
        public_name = tool.name
        if namespace is not None:
            public_name = f"{namespace}.{tool.name}"
        if public_name in self._entries:
            raise DuplicateToolError(f"Duplicate tool public name: {public_name}")

        try:
            Draft202012Validator.check_schema(tool.parameters)
        except SchemaError as e:
            raise InvalidToolSchemaError(f"{public_name} schema error: {e}") from e

        self._entries[public_name] = RegisteredTool(
            public_name=public_name,
            tool=tool,
            validator=Draft202012Validator(tool.parameters),
        )
        return public_name

    def start(self) -> None:
        # 只能在 OPEN 状态下进入
        if self.state is not ToolRegistryState.OPEN:
            raise ToolRegistryStateError("Register state is not open now")

        try:
            for registered_tool in self._entries.values():
                tool = registered_tool.tool
                if isinstance(tool, ManagedTool):
                    tool.start()
                    self._started_tools.append(tool)
        except BaseException as start_error:
            cleanup_errors: list[BaseException] = []
            for started_tool in reversed(self._started_tools):
                try:
                    started_tool.close()
                except BaseException as cleanup_error:  # noqa: BLE001
                    cleanup_errors.append(cleanup_error)
            self._started_tools.clear()
            self._state = ToolRegistryState.CLOSED
            for cleanup_error in cleanup_errors:
                start_error.add_note(f"Rollback close failed: {cleanup_error!r}")
            raise

        self._state = ToolRegistryState.STARTED

    def resolve(self, public_name: str) -> RegisteredTool | None:
        if self.state is not ToolRegistryState.STARTED:
            raise ToolRegistryStateError("Register state is not started now")

        if public_name in self._entries:
            return self._entries[public_name]

    def definitions(self) -> tuple[ToolDefinition, ...]:
        if self.state is not ToolRegistryState.STARTED:
            raise ToolRegistryStateError("Register state is not started now")
        tools: list[ToolDefinition] = []

        for registered_tool in self._entries.values():
            tools.append(registered_tool.definition())

        return tuple(tools)

    def close(self) -> None:
        if self.state is ToolRegistryState.CLOSED:
            return

        if self.state is ToolRegistryState.STARTED:
            for started_tool in reversed(self._started_tools):
                started_tool.close()

        # if self.state is ToolRegistryState.OPEN:

        self._state = ToolRegistryState.CLOSED
        self._started_tools.clear()
