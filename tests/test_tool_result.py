import unittest
from collections.abc import Mapping
from typing import Any, ClassVar

from agent_lab import (
    Agent,
    FinalAnswer,
    ToolCall,
    ToolErrorKind,
    ToolExecutionContext,
    ToolPermission,
    ToolResult,
)
from agent_lab.testing import RecordingTool, ScriptedModel


class ExplodingTool:
    name = "exploding"
    description = "Raise an unexpected programming error"
    permission = ToolPermission.READ
    supports_idempotency = False
    parameters: ClassVar[Mapping[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
    }

    def run(
        self,
        arguments: Mapping[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        raise RuntimeError("unexpected bug")


class ToolResultTests(unittest.TestCase):
    def test_success_contains_only_output(self) -> None:
        result = ToolResult.success("sunny")

        self.assertTrue(result.is_success)
        self.assertEqual("sunny", result.output)
        self.assertIsNone(result.error)

    def test_failure_contains_a_classified_error(self) -> None:
        result = ToolResult.failure(
            ToolErrorKind.EXECUTION_ERROR,
            "weather service unavailable",
            retryable=True,
        )

        self.assertFalse(result.is_success)
        self.assertIsNone(result.output)
        self.assertEqual(ToolErrorKind.EXECUTION_ERROR, result.error.kind)
        self.assertEqual("weather service unavailable", result.error.message)
        self.assertTrue(result.error.retryable)

    def test_result_rejects_ambiguous_states(self) -> None:
        with self.assertRaises(ValueError):
            ToolResult()

        with self.assertRaises(ValueError):
            ToolResult(
                output="sunny",
                error=ToolResult.failure(
                    ToolErrorKind.EXECUTION_ERROR,
                    "weather service unavailable",
                ).error,
            )

    def test_expected_tool_failure_is_returned_to_the_model(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": "Shanghai"}),
                FinalAnswer("暂时无法查询天气"),
            ]
        )
        weather = RecordingTool(
            "weather",
            ToolResult.failure(
                ToolErrorKind.EXECUTION_ERROR,
                "weather service unavailable",
            ),
        )

        result = Agent(model, [weather]).run("上海天气如何？")

        self.assertEqual("暂时无法查询天气", result.answer)
        observation = model.calls[1][0][-1]
        self.assertEqual("tool", observation.role)
        self.assertEqual("weather", observation.name)
        self.assertEqual(
            "Tool error [execution_error]: weather service unavailable",
            observation.content,
        )

    def test_unexpected_tool_exception_is_not_hidden(self) -> None:
        model = ScriptedModel([ToolCall("exploding", {})])

        with self.assertRaisesRegex(RuntimeError, "unexpected bug"):
            Agent(model, [ExplodingTool()]).run("触发工具")


if __name__ == "__main__":
    unittest.main()
