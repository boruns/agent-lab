import unittest

from agent_lab import (
    Agent,
    FinalAnswer,
    StepLimitExceeded,
    ToolCall,
    UnknownToolError,
)
from agent_lab.testing import RecordingTool, ScriptedModel


class AgentTests(unittest.TestCase):
    def test_tool_observation_is_returned_to_model_before_final_answer(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("calculator", {"expression": "6 * 7"}),
                FinalAnswer("结果是 42"),
            ]
        )
        calculator = RecordingTool("calculator", "42", "evaluate arithmetic")

        result = Agent(model, [calculator]).run("6 * 7 是多少？")

        self.assertEqual("结果是 42", result.answer)
        self.assertEqual(2, result.steps)
        self.assertEqual([{"expression": "6 * 7"}], calculator.calls)
        self.assertEqual("tool", model.calls[1][0][-1].role)
        self.assertEqual("calculator", model.calls[1][0][-1].name)
        self.assertEqual("42", model.calls[1][0][-1].content)

    def test_unknown_tool_is_rejected(self) -> None:
        model = ScriptedModel([ToolCall("shell", {"command": "whoami"})])

        with self.assertRaises(UnknownToolError):
            Agent(model).run("查看当前用户")

    def test_step_limit_stops_a_non_terminating_agent(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("clock", {}),
                ToolCall("clock", {}),
                FinalAnswer("不应该执行到这里"),
            ]
        )
        clock = RecordingTool("clock", "12:00")

        with self.assertRaises(StepLimitExceeded):
            Agent(model, [clock], max_steps=2).run("几点了？")

        self.assertEqual(2, len(clock.calls))


if __name__ == "__main__":
    unittest.main()
