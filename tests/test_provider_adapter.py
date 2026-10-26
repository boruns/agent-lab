import unittest
from collections.abc import Mapping
from typing import Any

from agent_lab import FinalAnswer, Message
from agent_lab.contracts import ToolDefinition
from agent_lab.providers import (
    DeepSeekResponsesAdapter,
    ProviderMappingError,
    ProviderToolNameCodec,
    UnsupportedProviderResponseError,
)


class RecordingTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self._response = response
        self.requests: list[dict[str, Any]] = []

    def create_response(
        self,
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        self.requests.append(dict(payload))
        return self._response


def completed_text_response(text: str) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


class ProviderToolNameCodecTests(unittest.TestCase):
    def test_name_mapping_is_readable_reversible_and_collision_free(self) -> None:
        expected = {
            "calculator": "calculator",
            "web.search": "web_dsearch",
            "docs.search_v2": "docs_dsearch_uv2",
            "docs.search-v2": "docs_dsearch-v2",
        }

        encoded_names = {
            ProviderToolNameCodec.encode(public_name) for public_name in expected
        }

        self.assertEqual(set(expected.values()), encoded_names)
        for public_name, provider_name in expected.items():
            with self.subTest(public_name=public_name):
                self.assertEqual(
                    public_name,
                    ProviderToolNameCodec.decode(provider_name),
                )

    def test_encoded_name_must_fit_the_provider_limit(self) -> None:
        public_name = f"namespace.{('a_' * 61)}tool"

        with self.assertRaisesRegex(ProviderMappingError, "128"):
            ProviderToolNameCodec.encode(public_name)

    def test_registry_names_are_validated_before_encoding(self) -> None:
        invalid_names = ["", "1tool", "bad name", "web..search", "web.search.more"]

        for public_name in invalid_names:
            with (
                self.subTest(public_name=public_name),
                self.assertRaises(ProviderMappingError),
            ):
                ProviderToolNameCodec.encode(public_name)

    def test_decode_rejects_unknown_incomplete_and_invalid_encodings(self) -> None:
        invalid_names = ["bad_xname", "bad_", "bad.name", "1tool"]

        for provider_name in invalid_names:
            with (
                self.subTest(provider_name=provider_name),
                self.assertRaises(ProviderMappingError),
            ):
                ProviderToolNameCodec.decode(provider_name)


class DeepSeekResponsesAdapterTests(unittest.TestCase):
    def test_request_maps_messages_tools_and_explicit_defaults(self) -> None:
        adapter = DeepSeekResponsesAdapter(
            "deepseek-flash",
            RecordingTransport(completed_text_response("unused")),
        )
        messages = [
            Message(role="user", content="search"),
            Message(role="assistant", content="I will search"),
        ]
        tools = [
            ToolDefinition(
                name="web.search",
                description="Search the web",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            )
        ]

        request = adapter.build_request(messages, tools)

        self.assertEqual(
            {
                "model": "deepseek-flash",
                "input": [
                    {"type": "message", "role": "user", "content": "search"},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": "I will search",
                    },
                ],
                "tools": [
                    {
                        "type": "function",
                        "name": "web_dsearch",
                        "description": "Search the web",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                            "additionalProperties": False,
                        },
                    }
                ],
                "reasoning": {"effort": "none"},
                "stream": False,
            },
            request,
        )

    def test_empty_tool_list_is_omitted(self) -> None:
        adapter = DeepSeekResponsesAdapter(
            "deepseek-flash",
            RecordingTransport(completed_text_response("unused")),
        )

        request = adapter.build_request([Message(role="user", content="hello")], [])

        self.assertNotIn("tools", request)

    def test_tool_history_is_rejected_until_call_ids_are_supported(self) -> None:
        adapter = DeepSeekResponsesAdapter(
            "deepseek-flash",
            RecordingTransport(completed_text_response("unused")),
        )

        with self.assertRaisesRegex(ProviderMappingError, "call ID"):
            adapter.build_request(
                [Message(role="tool", name="web.search", content="result")],
                [],
            )

    def test_decide_uses_transport_and_parses_final_answer(self) -> None:
        transport = RecordingTransport(completed_text_response("hello"))
        adapter = DeepSeekResponsesAdapter("deepseek-flash", transport)

        decision = adapter.decide([Message(role="user", content="hi")], [])

        self.assertEqual(FinalAnswer("hello"), decision)
        self.assertEqual(1, len(transport.requests))
        self.assertEqual("deepseek-flash", transport.requests[0]["model"])

    def test_incomplete_response_is_not_treated_as_a_final_answer(self) -> None:
        adapter = DeepSeekResponsesAdapter(
            "deepseek-flash",
            RecordingTransport({}),
        )

        with self.assertRaisesRegex(UnsupportedProviderResponseError, "incomplete"):
            adapter.parse_response(
                {
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                }
            )

    def test_function_call_is_not_silently_discarded(self) -> None:
        adapter = DeepSeekResponsesAdapter(
            "deepseek-flash",
            RecordingTransport({}),
        )

        with self.assertRaisesRegex(UnsupportedProviderResponseError, "lesson 12"):
            adapter.parse_response(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call_123",
                            "name": "web_dsearch",
                            "arguments": '{"query":"agents"}',
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
