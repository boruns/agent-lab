import unittest
from collections.abc import Mapping
from typing import Any

from agent_lab import (
    Agent,
    FinalAnswer,
    Message,
    ToolCall,
    ToolErrorKind,
    ToolRegistration,
    ToolResult,
)
from agent_lab.providers import (
    DeepSeekResponsesAdapter,
    ProviderMappingError,
    UnsupportedProviderResponseError,
)
from agent_lab.testing import RecordingTool, ScriptedModel


class StubTransport:
    def create_response(
        self,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        raise AssertionError(f"unexpected transport call: {payload!r}")


def function_call_response(
    *,
    arguments: str = '{"query":"agents"}',
) -> dict[str, Any]:
    return {
        "id": "resp_123",
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "id": "item_123",
                "status": "completed",
                "call_id": "call_123",
                "name": "web_dsearch",
                "arguments": arguments,
            }
        ],
    }


class FunctionCallResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DeepSeekResponsesAdapter("deepseek-flash", StubTransport())

    def test_single_function_call_becomes_provider_neutral_decision(self) -> None:
        decision = self.adapter.parse_response(function_call_response())

        self.assertEqual(
            ToolCall(
                name="web.search",
                arguments={"query": "agents"},
                call_id="call_123",
            ),
            decision,
        )

    def test_arguments_must_be_a_json_object(self) -> None:
        invalid_arguments = ["not-json", "[]", '"text"']

        for arguments in invalid_arguments:
            with (
                self.subTest(arguments=arguments),
                self.assertRaises(UnsupportedProviderResponseError),
            ):
                self.adapter.parse_response(function_call_response(arguments=arguments))

    def test_function_call_requires_non_empty_identity_fields(self) -> None:
        for field in ("call_id", "name"):
            with (
                self.subTest(field=field),
                self.assertRaises(UnsupportedProviderResponseError),
            ):
                response = function_call_response()
                response["output"][0][field] = ""
                self.adapter.parse_response(response)

    def test_multiple_function_calls_are_deferred_to_lesson_13(self) -> None:
        response = function_call_response()
        response["output"].append(
            {
                "type": "function_call",
                "status": "completed",
                "call_id": "call_456",
                "name": "web_dsearch",
                "arguments": '{"query":"providers"}',
            }
        )

        with self.assertRaisesRegex(
            UnsupportedProviderResponseError,
            "lesson 13",
        ):
            self.adapter.parse_response(response)


class FunctionCallHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DeepSeekResponsesAdapter("deepseek-flash", StubTransport())

    def test_call_and_result_are_replayed_as_linked_input_items(self) -> None:
        request = self.adapter.build_request(
            [
                Message(role="user", content="search for agents"),
                Message(
                    role="assistant",
                    content="",
                    name="web.search",
                    call_id="call_123",
                    arguments={"query": "agents"},
                ),
                Message(
                    role="tool",
                    content="result text",
                    name="web.search",
                    call_id="call_123",
                ),
            ],
            [],
        )

        self.assertEqual(
            [
                {
                    "type": "message",
                    "role": "user",
                    "content": "search for agents",
                },
                {
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "web_dsearch",
                    "arguments": '{"query":"agents"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_123",
                    "output": "result text",
                },
            ],
            request["input"],
        )

    def test_tool_result_requires_a_call_id(self) -> None:
        with self.assertRaisesRegex(ProviderMappingError, "call ID"):
            self.adapter.build_request(
                [Message(role="tool", content="orphan result", name="web.search")],
                [],
            )

    def test_history_rejects_mismatched_call_ids(self) -> None:
        with self.assertRaisesRegex(ProviderMappingError, "call ID"):
            self.adapter.build_request(
                [
                    Message(
                        role="assistant",
                        content="",
                        name="web.search",
                        call_id="call_123",
                        arguments={"query": "agents"},
                    ),
                    Message(
                        role="tool",
                        content="wrong result",
                        name="web.search",
                        call_id="call_456",
                    ),
                ],
                [],
            )

    def test_history_rejects_broken_call_result_pairs(self) -> None:
        call = Message(
            role="assistant",
            content="",
            name="web.search",
            call_id="call_123",
            arguments={"query": "agents"},
        )
        broken_histories = [
            [call],
            [call, Message(role="user", content="interrupt")],
            [
                call,
                Message(
                    role="tool",
                    content="wrong tool",
                    name="docs.search",
                    call_id="call_123",
                ),
            ],
        ]

        for messages in broken_histories:
            with (
                self.subTest(messages=messages),
                self.assertRaisesRegex(ProviderMappingError, "call ID"),
            ):
                self.adapter.build_request(messages, [])

    def test_agent_preserves_call_before_its_result(self) -> None:
        model = ScriptedModel(
            [
                ToolCall(
                    "web.search",
                    {"query": "agents"},
                    call_id="call_123",
                ),
                FinalAnswer("done"),
            ]
        )
        tool = RecordingTool("search", "result text")

        Agent(model, [ToolRegistration(tool, namespace="web")]).run("search for agents")

        second_turn = model.calls[1][0]
        self.assertEqual(["user", "assistant", "tool"], [m.role for m in second_turn])
        call, result = second_turn[-2:]
        self.assertEqual("call_123", call.call_id)
        self.assertEqual("web.search", call.name)
        self.assertEqual({"query": "agents"}, call.arguments)
        self.assertEqual("call_123", result.call_id)
        self.assertEqual("web.search", result.name)
        self.assertEqual("result text", result.content)

    def test_agent_links_expected_tool_errors_to_the_original_call(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": "Shanghai"}, call_id="call_123"),
                FinalAnswer("unavailable"),
            ]
        )
        tool = RecordingTool(
            "weather",
            ToolResult.failure(ToolErrorKind.EXECUTION_ERROR, "offline"),
        )

        Agent(model, [tool]).run("weather")

        call, result = model.calls[1][0][-2:]
        self.assertEqual("call_123", call.call_id)
        self.assertEqual("call_123", result.call_id)
        self.assertIn("execution_error", result.content)


if __name__ == "__main__":
    unittest.main()
