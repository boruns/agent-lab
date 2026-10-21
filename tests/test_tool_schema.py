import unittest

from agent_lab import Agent, CalculatorTool, FinalAnswer
from agent_lab.testing import ScriptedModel


class ToolSchemaTests(unittest.TestCase):
    def test_calculator_declares_its_input_as_json_schema(self) -> None:
        calculator = CalculatorTool()

        self.assertEqual("object", calculator.parameters["type"])
        self.assertEqual(
            "string",
            calculator.parameters["properties"]["expression"]["type"],
        )
        self.assertEqual(["expression"], calculator.parameters["required"])
        self.assertFalse(calculator.parameters["additionalProperties"])

    def test_agent_passes_tool_schema_to_the_model(self) -> None:
        calculator = CalculatorTool()
        model = ScriptedModel([FinalAnswer("准备完成")])

        Agent(model, [calculator]).run("计算 6 * 7")

        definitions = model.calls[0][1]
        self.assertEqual(1, len(definitions))
        self.assertEqual("calculator", definitions[0].name)
        self.assertEqual(calculator.parameters, definitions[0].parameters)


if __name__ == "__main__":
    unittest.main()
