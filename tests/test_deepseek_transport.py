import unittest
from typing import Any
from unittest.mock import patch

import httpx2
import openai

from agent_lab.deepseek import (
    DeepSeekResponsesTransport,
    DeepSeekSettings,
    ProviderCallRecord,
    ProviderErrorKind,
    ProviderTransportError,
    ProviderUsage,
    build_deepseek_transport,
)


def completed_response() -> dict[str, Any]:
    return {
        "id": "resp_123",
        "status": "completed",
        "model": "deepseek-flash",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "hello"}],
            }
        ],
        "usage": {
            "input_tokens": 12,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens": 8,
            "output_tokens_details": {"reasoning_tokens": 2},
            "total_tokens": 20,
        },
    }


class FakeSDKResponse:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        if mode != "json":
            raise AssertionError("transport must request JSON-compatible data")
        return self._data


class FakeResponsesResource:
    def __init__(
        self,
        *,
        response: FakeSDKResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> FakeSDKResponse:
        self.calls.append(payload)
        if self._error is not None:
            raise self._error
        if self._response is None:
            raise AssertionError("fake response was not configured")
        return self._response


class FakeClient:
    def __init__(self, responses: FakeResponsesResource) -> None:
        self.responses = responses


class DeepSeekSettingsTests(unittest.TestCase):
    def test_settings_are_loaded_from_an_explicit_environment_mapping(self) -> None:
        settings = DeepSeekSettings.from_env(
            {
                "DEEPSEEK_API_KEY": "secret",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.example",
                "DEEPSEEK_TIMEOUT_SECONDS": "12.5",
            }
        )

        self.assertEqual("secret", settings.api_key)
        self.assertEqual("deepseek-v4-pro", settings.model)
        self.assertEqual("https://api.deepseek.example", settings.base_url)
        self.assertEqual(12.5, settings.timeout)
        self.assertNotIn("secret", repr(settings))

    def test_settings_use_safe_non_secret_defaults(self) -> None:
        settings = DeepSeekSettings.from_env({"DEEPSEEK_API_KEY": "secret"})

        self.assertEqual("deepseek-flash", settings.model)
        self.assertEqual("https://api.deepseek.com", settings.base_url)
        self.assertEqual(30.0, settings.timeout)

    def test_missing_key_and_invalid_timeout_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_API_KEY"):
            DeepSeekSettings.from_env({})
        with self.assertRaisesRegex(ValueError, "DEEPSEEK_TIMEOUT_SECONDS"):
            DeepSeekSettings.from_env(
                {
                    "DEEPSEEK_API_KEY": "secret",
                    "DEEPSEEK_TIMEOUT_SECONDS": "not-a-number",
                }
            )


class DeepSeekResponsesTransportTests(unittest.TestCase):
    def test_factory_configures_sdk_timeout_and_disables_hidden_retries(self) -> None:
        settings = DeepSeekSettings(api_key="secret", timeout=17.0)

        with patch("agent_lab.deepseek.openai.OpenAI") as sdk_client:
            transport = build_deepseek_transport(settings)

        sdk_client.assert_called_once_with(
            api_key="secret",
            base_url="https://api.deepseek.com",
            timeout=17.0,
            max_retries=0,
        )
        self.assertIsInstance(transport, DeepSeekResponsesTransport)

    def test_success_returns_plain_mapping_and_records_usage(self) -> None:
        resource = FakeResponsesResource(response=FakeSDKResponse(completed_response()))
        records: list[ProviderCallRecord] = []
        transport = DeepSeekResponsesTransport(
            FakeClient(resource),
            record_call=records.append,
        )
        payload = {"model": "deepseek-flash", "input": "hello", "stream": False}

        response = transport.create_response(payload)

        self.assertEqual(completed_response(), response)
        self.assertEqual([payload], resource.calls)
        self.assertEqual(
            [
                ProviderCallRecord(
                    response_id="resp_123",
                    model="deepseek-flash",
                    usage=ProviderUsage(
                        input_tokens=12,
                        output_tokens=8,
                        total_tokens=20,
                        cached_tokens=3,
                        reasoning_tokens=2,
                    ),
                )
            ],
            records,
        )

    def test_sdk_errors_are_mapped_to_stable_categories(self) -> None:
        request = httpx2.Request("POST", "https://api.deepseek.com/responses")

        cases = [
            (
                openai.APITimeoutError(request),
                ProviderErrorKind.TIMEOUT,
                True,
                None,
            ),
            (
                openai.APIConnectionError(request=request),
                ProviderErrorKind.CONNECTION,
                True,
                None,
            ),
            (
                openai.AuthenticationError(
                    "bad key",
                    response=httpx2.Response(401, request=request),
                    body=None,
                ),
                ProviderErrorKind.AUTHENTICATION,
                False,
                401,
            ),
            (
                openai.RateLimitError(
                    "slow down",
                    response=httpx2.Response(429, request=request),
                    body=None,
                ),
                ProviderErrorKind.RATE_LIMIT,
                True,
                429,
            ),
            (
                openai.APIStatusError(
                    "request timeout",
                    response=httpx2.Response(408, request=request),
                    body=None,
                ),
                ProviderErrorKind.TIMEOUT,
                True,
                408,
            ),
            (
                openai.APIStatusError(
                    "balance",
                    response=httpx2.Response(402, request=request),
                    body=None,
                ),
                ProviderErrorKind.INSUFFICIENT_BALANCE,
                False,
                402,
            ),
            (
                openai.APIStatusError(
                    "bad request",
                    response=httpx2.Response(422, request=request),
                    body=None,
                ),
                ProviderErrorKind.INVALID_REQUEST,
                False,
                422,
            ),
            (
                openai.APIStatusError(
                    "overloaded",
                    response=httpx2.Response(503, request=request),
                    body=None,
                ),
                ProviderErrorKind.SERVER,
                True,
                503,
            ),
        ]

        for sdk_error, kind, retryable, status_code in cases:
            with self.subTest(kind=kind):
                transport = DeepSeekResponsesTransport(
                    FakeClient(FakeResponsesResource(error=sdk_error))
                )
                with self.assertRaises(ProviderTransportError) as raised:
                    transport.create_response({"model": "deepseek-flash"})

                self.assertEqual(kind, raised.exception.kind)
                self.assertEqual(retryable, raised.exception.retryable)
                self.assertEqual(status_code, raised.exception.status_code)

    def test_malformed_usage_is_a_protocol_error(self) -> None:
        response = completed_response()
        response["usage"] = {"input_tokens": 12}
        transport = DeepSeekResponsesTransport(
            FakeClient(FakeResponsesResource(response=FakeSDKResponse(response)))
        )

        with self.assertRaises(ProviderTransportError) as raised:
            transport.create_response({"model": "deepseek-flash"})

        self.assertEqual(ProviderErrorKind.PROTOCOL, raised.exception.kind)
        self.assertFalse(raised.exception.retryable)


if __name__ == "__main__":
    unittest.main()
