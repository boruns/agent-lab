import unittest
from collections.abc import Mapping
from threading import Event
from typing import Any

from agent_lab import (
    Agent,
    FinalAnswer,
    Message,
    ToolCall,
    ToolCallBatch,
    ToolExecutionContext,
    ToolPermission,
    ToolResult,
    UnknownToolError,
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


def function_call_item(
    call_id: str,
    name: str,
    arguments: str,
) -> dict[str, Any]:
    return {
        "type": "function_call",
        "status": "completed",
        "call_id": call_id,
        "name": name,
        "arguments": arguments,
    }


def batch_response() -> dict[str, Any]:
    return {
        "id": "resp_batch",
        "status": "completed",
        "output": [
            function_call_item(
                "call_search",
                "web_dsearch",
                '{"query":"agents"}',
            ),
            function_call_item(
                "call_weather",
                "weather",
                '{"city":"Shanghai"}',
            ),
        ],
    }


class FunctionCallBatchResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DeepSeekResponsesAdapter("deepseek-flash", StubTransport())

    def test_multiple_calls_become_one_ordered_batch(self) -> None:
        decision = self.adapter.parse_response(batch_response())

        self.assertEqual(
            ToolCallBatch(
                (
                    ToolCall(
                        "web.search",
                        {"query": "agents"},
                        call_id="call_search",
                    ),
                    ToolCall(
                        "weather",
                        {"city": "Shanghai"},
                        call_id="call_weather",
                    ),
                )
            ),
            decision,
        )

    def test_batch_rejects_duplicate_call_ids(self) -> None:
        response = batch_response()
        response["output"][1]["call_id"] = "call_search"

        with self.assertRaisesRegex(
            UnsupportedProviderResponseError,
            "call ID",
        ):
            self.adapter.parse_response(response)

    def test_batch_rejects_mixed_output_types(self) -> None:
        response = batch_response()
        response["output"].append(
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done"}],
            }
        )

        with self.assertRaises(UnsupportedProviderResponseError):
            self.adapter.parse_response(response)


class FunctionCallBatchHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DeepSeekResponsesAdapter("deepseek-flash", StubTransport())

    @staticmethod
    def messages() -> list[Message]:
        return [
            Message(role="user", content="search and check weather"),
            Message(
                role="assistant",
                content="",
                name="web.search",
                call_id="call_search",
                arguments={"query": "agents"},
            ),
            Message(
                role="assistant",
                content="",
                name="weather",
                call_id="call_weather",
                arguments={"city": "Shanghai"},
            ),
            Message(
                role="tool",
                content="search result",
                name="web.search",
                call_id="call_search",
            ),
            Message(
                role="tool",
                content="sunny",
                name="weather",
                call_id="call_weather",
            ),
        ]

    def test_batch_history_replays_calls_then_ordered_outputs(self) -> None:
        request = self.adapter.build_request(self.messages(), [])

        self.assertEqual(
            [
                {
                    "type": "function_call",
                    "call_id": "call_search",
                    "name": "web_dsearch",
                    "arguments": '{"query":"agents"}',
                },
                {
                    "type": "function_call",
                    "call_id": "call_weather",
                    "name": "weather",
                    "arguments": '{"city":"Shanghai"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_search",
                    "output": "search result",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_weather",
                    "output": "sunny",
                },
            ],
            request["input"][1:],
        )

    def test_batch_history_rejects_missing_or_reordered_outputs(self) -> None:
        missing = self.messages()[:-1]
        reordered = self.messages()[:3] + list(reversed(self.messages()[3:]))

        for messages in (missing, reordered):
            with (
                self.subTest(messages=messages),
                self.assertRaisesRegex(ProviderMappingError, "call ID"),
            ):
                self.adapter.build_request(messages, [])


class OrderedRecordingTool(RecordingTool):
    def __init__(self, name: str, result: str, events: list[str]) -> None:
        super().__init__(name, result)
        self._events = events

    def run(
        self,
        arguments: Mapping[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        self._events.append(self.name)
        return super().run(arguments, context=context)


class RendezvousReadTool(RecordingTool):
    def __init__(
        self,
        name: str,
        own_started: Event,
        other_started: Event,
    ) -> None:
        super().__init__(name, f"{name} result", permission=ToolPermission.READ)
        self._own_started = own_started
        self._other_started = other_started

    def run(
        self,
        arguments: Mapping[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        self._own_started.set()
        if not self._other_started.wait(timeout=2):
            raise AssertionError("read-only batch calls did not overlap")
        return super().run(arguments, context=context)


class SequencedWriteTool(RecordingTool):
    def __init__(
        self,
        name: str,
        *,
        first: bool,
        first_finished: Event,
        second_started: Event,
        overlap_detected: Event,
    ) -> None:
        super().__init__(name, f"{name} result", permission=ToolPermission.WRITE)
        self._first = first
        self._first_finished = first_finished
        self._second_started = second_started
        self._overlap_detected = overlap_detected

    def run(
        self,
        arguments: Mapping[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        if self._first:
            if self._second_started.wait(timeout=0.2):
                self._overlap_detected.set()
            self._first_finished.set()
        else:
            self._second_started.set()
            if not self._first_finished.is_set():
                self._overlap_detected.set()
        return super().run(arguments, context=context)


class ToolCallBatchAgentTests(unittest.TestCase):
    @staticmethod
    def decision() -> ToolCallBatch:
        return ToolCallBatch(
            (
                ToolCall("search", {"query": "agents"}, call_id="call_search"),
                ToolCall(
                    "weather",
                    {"city": "Shanghai"},
                    call_id="call_weather",
                ),
            )
        )

    def test_default_execution_is_sequential_and_history_is_grouped(self) -> None:
        events: list[str] = []
        model = ScriptedModel([self.decision(), FinalAnswer("done")])
        tools = [
            OrderedRecordingTool("search", "search result", events),
            OrderedRecordingTool("weather", "sunny", events),
        ]

        Agent(model, tools).run("search and check weather")

        self.assertEqual(["search", "weather"], events)
        second_turn = model.calls[1][0]
        self.assertEqual(
            ["user", "assistant", "assistant", "tool", "tool"],
            [message.role for message in second_turn],
        )
        self.assertEqual(
            ["call_search", "call_weather", "call_search", "call_weather"],
            [message.call_id for message in second_turn[1:]],
        )

    def test_parallel_read_calls_overlap_but_history_stays_ordered(self) -> None:
        search_started = Event()
        weather_started = Event()
        search = RendezvousReadTool("search", search_started, weather_started)
        weather = RendezvousReadTool("weather", weather_started, search_started)
        model = ScriptedModel([self.decision(), FinalAnswer("done")])

        Agent(
            model,
            [search, weather],
            parallel_tool_calls=True,
            max_parallel_tools=2,
        ).run("search and check weather")

        second_turn = model.calls[1][0]
        self.assertEqual(
            ["call_search", "call_weather"],
            [message.call_id for message in second_turn[-2:]],
        )

    def test_duplicate_ids_fail_before_any_tool_runs(self) -> None:
        search = RecordingTool("search", "search result")
        weather = RecordingTool("weather", "sunny")
        decision = ToolCallBatch(
            (
                ToolCall("search", {}, call_id="duplicate"),
                ToolCall("weather", {}, call_id="duplicate"),
            )
        )

        with self.assertRaisesRegex(ValueError, "call ID"):
            Agent(ScriptedModel([decision]), [search, weather]).run("run both")

        self.assertEqual([], search.calls)
        self.assertEqual([], weather.calls)

    def test_unknown_tool_fails_preflight_before_any_tool_runs(self) -> None:
        search = RecordingTool("search", "search result")
        decision = ToolCallBatch(
            (
                ToolCall("search", {}, call_id="call_search"),
                ToolCall("missing", {}, call_id="call_missing"),
            )
        )

        with self.assertRaises(UnknownToolError):
            Agent(ScriptedModel([decision]), [search]).run("run both")

        self.assertEqual([], search.calls)

    def test_invalid_arguments_do_not_block_other_calls(self) -> None:
        search = RecordingTool(
            "search",
            "search result",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        )
        weather = RecordingTool("weather", "sunny")
        decision = ToolCallBatch(
            (
                ToolCall("search", {"query": 42}, call_id="call_search"),
                ToolCall("weather", {}, call_id="call_weather"),
            )
        )
        model = ScriptedModel([decision, FinalAnswer("done")])

        Agent(model, [search, weather]).run("run both")

        self.assertEqual([], search.calls)
        self.assertEqual([{}], weather.calls)
        search_result, weather_result = model.calls[1][0][-2:]
        self.assertEqual("call_search", search_result.call_id)
        self.assertIn("invalid_arguments", search_result.content)
        self.assertEqual("call_weather", weather_result.call_id)
        self.assertEqual("sunny", weather_result.content)

    def test_write_calls_remain_sequential_when_parallel_is_enabled(self) -> None:
        first_finished = Event()
        second_started = Event()
        overlap_detected = Event()
        first = SequencedWriteTool(
            "first_write",
            first=True,
            first_finished=first_finished,
            second_started=second_started,
            overlap_detected=overlap_detected,
        )
        second = SequencedWriteTool(
            "second_write",
            first=False,
            first_finished=first_finished,
            second_started=second_started,
            overlap_detected=overlap_detected,
        )
        decision = ToolCallBatch(
            (
                ToolCall("first_write", {}, call_id="call_first"),
                ToolCall("second_write", {}, call_id="call_second"),
            )
        )
        model = ScriptedModel([decision, FinalAnswer("done")])

        Agent(
            model,
            [first, second],
            allowed_permissions=(ToolPermission.READ, ToolPermission.WRITE),
            confirmation_handler=lambda _request: True,
            parallel_tool_calls=True,
            max_parallel_tools=2,
        ).run("run both")

        self.assertFalse(overlap_detected.is_set())


if __name__ == "__main__":
    unittest.main()
