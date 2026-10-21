import unittest
from types import MappingProxyType

from agent_lab import (
    Agent,
    FinalAnswer,
    InvalidToolSchemaError,
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
    def test_tools_can_be_supplied_as_a_single_pass_iterable(self) -> None:
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
        tools = (tool for tool in [weather])

        result = Agent(model, tools).run("上海天气如何？")

        self.assertEqual("上海天气已查询", result.answer)
        self.assertEqual([{"city": "Shanghai"}], weather.calls)

    def test_mapping_arguments_are_validated_as_a_json_object(self) -> None:
        arguments = MappingProxyType({"city": "Shanghai"})
        model = ScriptedModel(
            [
                ToolCall("weather", arguments),
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
        self.assertEqual([arguments], weather.calls)

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

    def test_invalid_arguments_are_returned_to_the_model_for_correction(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": 42}),
                ToolCall("weather", {"city": "Shanghai"}),
                FinalAnswer("上海天气已查询"),
            ]
        )
        weather = RecordingTool(
            "weather",
            "sunny",
            parameters=CITY_PARAMETERS,
        )

        result = Agent(model, [weather]).run("查询上海的天气")

        self.assertEqual("上海天气已查询", result.answer)
        self.assertEqual([{"city": "Shanghai"}], weather.calls)
        error_observation = model.calls[1][0][-1]
        self.assertEqual("tool", error_observation.role)
        self.assertEqual("weather", error_observation.name)
        self.assertIn("invalid_arguments", error_observation.content)
        self.assertIn("42 is not of type 'string'", error_observation.content)

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
