"""DeepSeek configuration and synchronous Responses API transport."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from os import environ
from typing import Any, Protocol, cast

import openai


class ProviderErrorKind(StrEnum):
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    AUTHENTICATION = "authentication"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    RATE_LIMIT = "rate_limit"
    INVALID_REQUEST = "invalid_request"
    SERVER = "server"
    PROTOCOL = "protocol"
    UNKNOWN = "unknown"


class ProviderTransportError(RuntimeError):
    """A stable provider-neutral failure produced by the transport boundary."""

    def __init__(
        self,
        message: str,
        *,
        kind: ProviderErrorKind,
        retryable: bool,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cached_tokens,
            self.reasoning_tokens,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) for value in values
        ):
            raise TypeError("token usage values must be integers")
        if any(value < 0 for value in values):
            raise ValueError("token usage values must not be negative")
        if self.cached_tokens > self.input_tokens:
            raise ValueError("cached_tokens must not exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens must not exceed output_tokens")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")


@dataclass(frozen=True)
class ProviderCallRecord:
    response_id: str
    model: str
    usage: ProviderUsage


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str = field(repr=False)
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com"
    timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("DEEPSEEK_API_KEY must not be empty")
        if not self.model.strip():
            raise ValueError("DEEPSEEK_MODEL must not be empty")
        if not self.base_url.startswith("https://"):
            raise ValueError("DEEPSEEK_BASE_URL must use https")
        if not isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("DEEPSEEK_TIMEOUT_SECONDS must be positive")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DeepSeekSettings:
        """Read and validate configuration without logging secrets."""
        envs = environ if env is None else env
        api_key = (envs.get("DEEPSEEK_API_KEY") or "").strip()
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY must not be empty")

        model = (envs.get("DEEPSEEK_MODEL") or cls.model).strip()
        base_url = (envs.get("DEEPSEEK_BASE_URL") or cls.base_url).strip()
        raw_timeout = envs.get("DEEPSEEK_TIMEOUT_SECONDS")
        try:
            timeout = cls.timeout if raw_timeout is None else float(raw_timeout)
        except ValueError as error:
            raise ValueError("DEEPSEEK_TIMEOUT_SECONDS must be a number") from error

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
        )


class SDKResponse(Protocol):
    def model_dump(self, *, mode: str) -> dict[str, Any]: ...


class ResponsesResource(Protocol):
    def create(self, **payload: Any) -> SDKResponse: ...


class ResponsesClient(Protocol):
    responses: ResponsesResource


type CallRecorder = Callable[[ProviderCallRecord], None]


def _protocol_error(message: str) -> ProviderTransportError:
    return ProviderTransportError(
        message,
        kind=ProviderErrorKind.PROTOCOL,
        retryable=False,
    )


def _required_string(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value:
        raise _protocol_error(f"Response {name} must be a non-empty string")
    return value


def _required_token_count(data: Mapping[str, Any], name: str) -> int:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _protocol_error(f"Response usage {name} must be an integer")
    return value


def _optional_details(
    usage: Mapping[str, Any],
    name: str,
) -> Mapping[str, Any]:
    if name not in usage:
        return {}
    details = usage[name]
    if not isinstance(details, Mapping):
        raise _protocol_error(f"Response usage {name} must be a mapping")
    return details


def _classify_status(status_code: int) -> tuple[ProviderErrorKind, bool]:
    match status_code:
        case 408:
            return ProviderErrorKind.TIMEOUT, True
        case 401:
            return ProviderErrorKind.AUTHENTICATION, False
        case 402:
            return ProviderErrorKind.INSUFFICIENT_BALANCE, False
        case 429:
            return ProviderErrorKind.RATE_LIMIT, True
        case 400 | 422:
            return ProviderErrorKind.INVALID_REQUEST, False
        case code if code >= 500:
            return ProviderErrorKind.SERVER, True
        case _:
            return ProviderErrorKind.UNKNOWN, False


class DeepSeekResponsesTransport:
    """Call an SDK client and return plain JSON-compatible mappings."""

    def __init__(
        self,
        client: ResponsesClient,
        *,
        record_call: CallRecorder | None = None,
    ) -> None:
        self._client = client
        self._record_call = record_call

    def create_response(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            response = self._client.responses.create(**dict(payload))
        except openai.APITimeoutError as error:
            raise ProviderTransportError(
                "DeepSeek API request timed out",
                kind=ProviderErrorKind.TIMEOUT,
                retryable=True,
            ) from error
        except openai.APIConnectionError as error:
            raise ProviderTransportError(
                "Could not connect to the DeepSeek API",
                kind=ProviderErrorKind.CONNECTION,
                retryable=True,
            ) from error
        except openai.APIStatusError as error:
            kind, retryable = _classify_status(error.status_code)
            raise ProviderTransportError(
                f"DeepSeek API returned HTTP {error.status_code}",
                kind=kind,
                retryable=retryable,
                status_code=error.status_code,
            ) from error
        except openai.APIError as error:
            raise ProviderTransportError(
                "DeepSeek SDK returned an unknown API error",
                kind=ProviderErrorKind.UNKNOWN,
                retryable=False,
            ) from error

        result = response.model_dump(mode="json")
        if not isinstance(result, Mapping):
            raise _protocol_error("Response must be a mapping")

        response_id = _required_string(result, "id")
        model = _required_string(result, "model")
        usage = result.get("usage")
        if not isinstance(usage, Mapping):
            raise _protocol_error("Response usage must be a mapping")

        input_details = _optional_details(usage, "input_tokens_details")
        output_details = _optional_details(usage, "output_tokens_details")
        try:
            provider_usage = ProviderUsage(
                input_tokens=_required_token_count(usage, "input_tokens"),
                output_tokens=_required_token_count(usage, "output_tokens"),
                total_tokens=_required_token_count(usage, "total_tokens"),
                cached_tokens=_required_token_count(
                    input_details,
                    "cached_tokens",
                )
                if "cached_tokens" in input_details
                else 0,
                reasoning_tokens=_required_token_count(
                    output_details,
                    "reasoning_tokens",
                )
                if "reasoning_tokens" in output_details
                else 0,
            )
        except (TypeError, ValueError) as error:
            raise _protocol_error(str(error)) from error

        record = ProviderCallRecord(
            response_id=response_id,
            model=model,
            usage=provider_usage,
        )
        if self._record_call is not None:
            self._record_call(record)

        return result


def build_deepseek_transport(
    settings: DeepSeekSettings,
    *,
    record_call: CallRecorder | None = None,
) -> DeepSeekResponsesTransport:
    """Create the real SDK client with explicit timeout and retry ownership."""
    client = openai.OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
        max_retries=0,  # 禁止重试，明确由上层来重试
    )
    # The SDK's overloads are wider than our synchronous, non-streaming protocol.
    typed_client = cast(ResponsesClient, client)
    return DeepSeekResponsesTransport(
        client=typed_client,
        record_call=record_call,
    )
