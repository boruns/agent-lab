import unittest

from agent_lab import (
    Agent,
    FinalAnswer,
    InvalidToolSchemaError,
    ToolArgumentsValidationError,
    ToolCall,
)
from agent_lab.testing import RecordingTool, ScriptedModel

CITY_PARAMETERS = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}


class ToolValidationTests(unittest.TestCase):
    def test_valid_arguments_reach_the_tool(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": "Shanghai"}),
                FinalAnswer("上海天气已查询"),
            ]
        )
        weather = RecordingTool(
            "weather",
            "sunny",
            parameters=CITY_PARAMETERS,
        )

        result = Agent(model, [weather]).run("上海天气如何？")

        self.assertEqual("上海天气已查询", result.answer)
        self.assertEqual([{"city": "Shanghai"}], weather.calls)

    def test_invalid_arguments_are_rejected_before_execution(self) -> None:
        model = ScriptedModel([ToolCall("weather", {"city": 42})])
        weather = RecordingTool(
            "weather",
            "should not execute",
            parameters=CITY_PARAMETERS,
        )

        with self.assertRaisesRegex(
            ToolArgumentsValidationError,
            "weather",
        ):
            Agent(model, [weather]).run("查询城市 42 的天气")

        self.assertEqual([], weather.calls)

    def test_invalid_tool_schema_is_rejected_during_agent_setup(self) -> None:
        invalid_schema = {
            "type": "not-a-real-json-schema-type",
        }
        broken_tool = RecordingTool(
            "broken",
            "should not execute",
            parameters=invalid_schema,
        )

        with self.assertRaisesRegex(InvalidToolSchemaError, "broken"):
            Agent(ScriptedModel([]), [broken_tool])


if __name__ == "__main__":
    unittest.main()
