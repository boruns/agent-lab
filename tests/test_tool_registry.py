import unittest

from agent_lab import (
    Agent,
    DuplicateToolError,
    FinalAnswer,
    InvalidToolNameError,
    ToolCall,
    ToolRegistration,
    ToolRegistry,
    ToolRegistryState,
    ToolRegistryStateError,
)
from agent_lab.testing import RecordingTool, ScriptedModel


class LifecycleTool(RecordingTool):
    def __init__(
        self,
        name: str,
        events: list[str],
        *,
        fail_on_start: bool = False,
        fail_on_close: bool = False,
    ) -> None:
        super().__init__(name, f"{name} result")
        self._events = events
        self._fail_on_start = fail_on_start
        self._fail_on_close = fail_on_close

    def start(self) -> None:
        self._events.append(f"start:{self.name}")
        if self._fail_on_start:
            raise RuntimeError(f"failed to start {self.name}")

    def close(self) -> None:
        self._events.append(f"close:{self.name}")
        if self._fail_on_close:
            raise RuntimeError(f"failed to close {self.name}")


class ToolRegistryTests(unittest.TestCase):
    def test_duplicate_public_name_is_rejected_instead_of_overwritten(self) -> None:
        registry = ToolRegistry()
        first = RecordingTool("search", "first")
        second = RecordingTool("search", "second")

        registry.register(first)

        with self.assertRaisesRegex(DuplicateToolError, "search"):
            registry.register(second)

    def test_same_local_name_is_allowed_in_different_namespaces(self) -> None:
        registry = ToolRegistry()
        web_search = RecordingTool("search", "web result")
        docs_search = RecordingTool("search", "docs result")

        self.assertEqual("web.search", registry.register(web_search, namespace="web"))
        self.assertEqual(
            "docs.search", registry.register(docs_search, namespace="docs")
        )
        registry.start()

        self.assertIs(web_search, registry.resolve("web.search").tool)
        self.assertIs(docs_search, registry.resolve("docs.search").tool)
        self.assertEqual(
            ["web.search", "docs.search"],
            [definition.name for definition in registry.definitions()],
        )

    def test_name_segments_are_unambiguous(self) -> None:
        invalid_cases = [
            ("bad.name", None),
            ("two words", None),
            ("search", "bad.namespace"),
            ("search", "two words"),
            ("1search", None),
        ]

        for local_name, namespace in invalid_cases:
            with self.subTest(local_name=local_name, namespace=namespace):
                registry = ToolRegistry()
                tool = RecordingTool(local_name, "result")
                with self.assertRaises(InvalidToolNameError):
                    registry.register(tool, namespace=namespace)

    def test_start_freezes_registration_and_close_disables_lookup(self) -> None:
        registry = ToolRegistry([RecordingTool("search", "result")])
        registry.start()

        with self.assertRaises(ToolRegistryStateError):
            registry.register(RecordingTool("weather", "sunny"))

        registry.close()

        self.assertEqual(ToolRegistryState.CLOSED, registry.state)
        with self.assertRaises(ToolRegistryStateError):
            registry.resolve("search")
        with self.assertRaises(ToolRegistryStateError):
            registry.definitions()

    def test_managed_tools_start_in_order_and_close_in_reverse_once(self) -> None:
        events: list[str] = []
        registry = ToolRegistry(
            [
                LifecycleTool("first", events),
                LifecycleTool("second", events),
            ]
        )

        registry.start()
        registry.close()
        registry.close()

        self.assertEqual(
            ["start:first", "start:second", "close:second", "close:first"],
            events,
        )

    def test_start_failure_rolls_back_already_started_tools(self) -> None:
        events: list[str] = []
        registry = ToolRegistry(
            [
                LifecycleTool("first", events),
                LifecycleTool("broken", events, fail_on_start=True),
                LifecycleTool("never-started", events),
            ]
        )

        with self.assertRaisesRegex(RuntimeError, "failed to start broken"):
            registry.start()

        self.assertEqual(
            ["start:first", "start:broken", "close:first"],
            events,
        )
        self.assertEqual(ToolRegistryState.CLOSED, registry.state)

    def test_close_reports_all_failures_without_repeating_tools(self) -> None:
        events: list[str] = []
        registry = ToolRegistry(
            [
                LifecycleTool("first", events, fail_on_close=True),
                LifecycleTool("second", events, fail_on_close=True),
                LifecycleTool("third", events),
            ]
        )
        registry.start()

        with self.assertRaises(ExceptionGroup) as raised:
            registry.close()

        self.assertEqual(
            [
                "start:first",
                "start:second",
                "start:third",
                "close:third",
                "close:second",
                "close:first",
            ],
            events,
        )
        self.assertEqual(
            ["failed to close second", "failed to close first"],
            [str(error) for error in raised.exception.exceptions],
        )
        self.assertEqual(ToolRegistryState.CLOSED, registry.state)

        registry.close()
        self.assertEqual(6, len(events))

    def test_agent_rejects_duplicate_tools_during_setup(self) -> None:
        tools = [
            RecordingTool("search", "first"),
            RecordingTool("search", "second"),
        ]

        with self.assertRaises(DuplicateToolError):
            Agent(ScriptedModel([]), tools)

    def test_agent_uses_qualified_names_and_owns_the_registry_lifecycle(self) -> None:
        events: list[str] = []
        search = LifecycleTool("search", events)
        model = ScriptedModel(
            [ToolCall("web.search", {"query": "agents"}), FinalAnswer("done")]
        )

        with Agent(model, [ToolRegistration(search, namespace="web")]) as agent:
            result = agent.run("search")
            self.assertEqual(["start:search"], events)

        self.assertEqual("done", result.answer)
        self.assertEqual(["start:search", "close:search"], events)
        self.assertEqual("web.search", model.calls[0][1][0].name)
        self.assertEqual("web.search", model.calls[1][0][-1].name)


if __name__ == "__main__":
    unittest.main()
