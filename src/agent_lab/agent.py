"""The control loop for a minimal tool-using agent."""

from __future__ import annotations

from collections.abc import Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .contracts import (
    FinalAnswer,
    Message,
    Model,
    RunResult,
    Tool,
    ToolCall,
    ToolDefinition,
)


class UnknownToolError(LookupError):
    """Raised when a model asks for a tool that the host did not provide."""


class StepLimitExceeded(RuntimeError):
    """Raised when an agent does not finish inside its execution budget."""


class InvalidToolSchemaError(ValueError):
    """Raised when a tool declares an invalid JSON Schema."""


class ToolArgumentsValidationError(ValueError):
    """Raised before execution when tool arguments do not match its schema."""


class Agent:
    def __init__(
        self,
        model: Model,
        tools: Iterable[Tool] = (),
        *,
        max_steps: int = 8,
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

    def run(self, question: str) -> RunResult:
        """Run until the model answers or the step budget is exhausted.

        This method is intentionally left as the first exercise. Read
        docs/01-foundations/01-minimal-react-agent.md, then make the tests pass without
        changing the public contracts.
        """
        history: list[Message] = [Message(role="user", content=question)]
        tools = tuple(
            ToolDefinition(
                name=tool.name, description=tool.description, parameters=tool.parameters
            )
            for tool, _ in self._tools.values()
        )
        for step in range(self._max_steps):
            decision = self._model.decide(history, tools)
            if isinstance(decision, FinalAnswer):
                history.append(Message(role="assistant", content=decision.content))
                return RunResult(
                    answer=decision.content,
                    steps=step + 1,
                    messages=tuple(history),
                )
            if isinstance(decision, ToolCall):
                result = self._tools.get(decision.name)
                if result is None:
                    raise UnknownToolError(
                        f"Model requested unknown tool: {decision.name}"
                    )
                tool, validator = result
                try:
                    validator.validate(dict(decision.arguments))
                except ValidationError as e:
                    raise ToolArgumentsValidationError(
                        f"tool {decision.name} arguments validation error: {e.message}"
                    ) from e
                observation = tool.run(decision.arguments)
                history.append(
                    Message(role="tool", content=observation, name=tool.name)
                )
        raise StepLimitExceeded("Step limit exceeded")
