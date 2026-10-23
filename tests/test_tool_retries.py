import unittest

from agent_lab import (
    Agent,
    AgentCancelledError,
    AgentTimeoutError,
    CancellationToken,
    FinalAnswer,
    RetryPolicy,
    ToolCall,
    ToolErrorKind,
    ToolResult,
)
from agent_lab.testing import ScriptedModel, ScriptedTool


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.current

    def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.current += delay


class AdvancingModel:
    def __init__(
        self,
        clock: FakeClock,
        *,
        advance: float = 0.0,
        cancellation_token: CancellationToken | None = None,
    ) -> None:
        self._clock = clock
        self._advance = advance
        self._cancellation_token = cancellation_token
        self.calls = 0

    def decide(self, messages, tools):
        self.calls += 1
        self._clock.current += self._advance
        if self._cancellation_token is not None:
            self._cancellation_token.cancel()
        return FinalAnswer("late answer")


class AdvancingTool(ScriptedTool):
    def __init__(self, clock: FakeClock, advance: float) -> None:
        super().__init__("clock", [ToolResult.success("late result")])
        self._clock = clock
        self._advance = advance

    def run(self, arguments):
        self._clock.current += self._advance
        return super().run(arguments)


def retryable_failure(message: str = "temporary outage") -> ToolResult:
    return ToolResult.failure(
        ToolErrorKind.EXECUTION_ERROR,
        message,
        retryable=True,
    )


class RetryPolicyTests(unittest.TestCase):
    def test_exponential_backoff_is_capped(self) -> None:
        policy = RetryPolicy(
            initial_delay=0.25,
            backoff_multiplier=2,
            max_delay=0.75,
        )

        self.assertEqual(0.25, policy.delay_after(1))
        self.assertEqual(0.5, policy.delay_after(2))
        self.assertEqual(0.75, policy.delay_after(3))
        self.assertEqual(0.75, policy.delay_after(4))

    def test_invalid_retry_policy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)
        with self.assertRaises(ValueError):
            RetryPolicy(initial_delay=-1)
        with self.assertRaises(ValueError):
            RetryPolicy(backoff_multiplier=0.5)


class ToolRetryTests(unittest.TestCase):
    def test_negative_timeout_is_rejected_before_calling_the_model(self) -> None:
        model = ScriptedModel([FinalAnswer("不应执行")])

        with self.assertRaisesRegex(ValueError, "timeout"):
            Agent(model).run("问题", timeout=-1)

        self.assertEqual([], model.calls)

    def test_timeout_is_checked_after_the_model_returns(self) -> None:
        clock = FakeClock()
        model = AdvancingModel(clock, advance=1.0)
        agent = Agent(model, clock=clock.now, sleep=clock.sleep)

        with self.assertRaises(AgentTimeoutError):
            agent.run("问题", timeout=0.5)

        self.assertEqual(1, model.calls)

    def test_timeout_is_checked_after_the_tool_returns(self) -> None:
        clock = FakeClock()
        model = ScriptedModel([ToolCall("clock", {})])
        tool = AdvancingTool(clock, advance=1.0)
        agent = Agent(model, [tool], clock=clock.now, sleep=clock.sleep)

        with self.assertRaises(AgentTimeoutError):
            agent.run("运行慢工具", timeout=0.5)

        self.assertEqual(1, len(tool.calls))
        self.assertEqual(1, len(model.calls))

    def test_cancellation_is_checked_after_the_model_returns(self) -> None:
        clock = FakeClock()
        token = CancellationToken()
        model = AdvancingModel(clock, cancellation_token=token)
        agent = Agent(model, clock=clock.now, sleep=clock.sleep)

        with self.assertRaises(AgentCancelledError):
            agent.run("问题", cancellation_token=token)

        self.assertEqual(1, model.calls)

    def test_retryable_failure_is_retried_before_returning_to_model(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": "Shanghai"}),
                FinalAnswer("上海天气晴朗"),
            ]
        )
        weather = ScriptedTool(
            "weather",
            [retryable_failure(), ToolResult.success("sunny")],
        )
        clock = FakeClock()
        agent = Agent(
            model,
            [weather],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.25),
            clock=clock.now,
            sleep=clock.sleep,
        )

        result = agent.run("上海天气如何？")

        self.assertEqual("上海天气晴朗", result.answer)
        self.assertEqual(2, len(weather.calls))
        self.assertEqual([0.25], clock.sleeps)
        self.assertEqual("sunny", model.calls[1][0][-1].content)

    def test_non_retryable_failure_is_returned_without_retry(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": "Shanghai"}),
                FinalAnswer("暂时无法查询"),
            ]
        )
        weather = ScriptedTool(
            "weather",
            [
                ToolResult.failure(
                    ToolErrorKind.EXECUTION_ERROR,
                    "account disabled",
                )
            ],
        )
        clock = FakeClock()
        agent = Agent(
            model,
            [weather],
            retry_policy=RetryPolicy(max_attempts=3),
            clock=clock.now,
            sleep=clock.sleep,
        )

        agent.run("上海天气如何？")

        self.assertEqual(1, len(weather.calls))
        self.assertEqual([], clock.sleeps)

    def test_retry_stops_at_max_attempts_and_returns_last_failure(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("weather", {"city": "Shanghai"}),
                FinalAnswer("暂时无法查询"),
            ]
        )
        weather = ScriptedTool(
            "weather",
            [
                retryable_failure("failure 1"),
                retryable_failure("failure 2"),
                retryable_failure("failure 3"),
            ],
        )
        clock = FakeClock()
        agent = Agent(
            model,
            [weather],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.25),
            clock=clock.now,
            sleep=clock.sleep,
        )

        agent.run("上海天气如何？")

        self.assertEqual(3, len(weather.calls))
        self.assertEqual([0.25, 0.5], clock.sleeps)
        self.assertEqual(
            "Tool error [execution_error]: failure 3",
            model.calls[1][0][-1].content,
        )

    def test_timeout_prevents_a_retry_that_would_exceed_deadline(self) -> None:
        model = ScriptedModel([ToolCall("weather", {"city": "Shanghai"})])
        weather = ScriptedTool("weather", [retryable_failure()])
        clock = FakeClock()
        agent = Agent(
            model,
            [weather],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.5),
            clock=clock.now,
            sleep=clock.sleep,
        )

        with self.assertRaises(AgentTimeoutError):
            agent.run("上海天气如何？", timeout=0.25)

        self.assertEqual(1, len(weather.calls))
        self.assertEqual([], clock.sleeps)

    def test_pre_cancelled_run_does_not_call_the_model(self) -> None:
        model = ScriptedModel([FinalAnswer("不应执行")])
        token = CancellationToken()
        token.cancel()

        with self.assertRaises(AgentCancelledError):
            Agent(model).run("问题", cancellation_token=token)

        self.assertEqual([], model.calls)

    def test_cancellation_during_backoff_prevents_the_next_attempt(self) -> None:
        model = ScriptedModel([ToolCall("weather", {"city": "Shanghai"})])
        weather = ScriptedTool("weather", [retryable_failure()])
        token = CancellationToken()

        def cancel_during_sleep(delay: float) -> None:
            token.cancel()

        agent = Agent(
            model,
            [weather],
            retry_policy=RetryPolicy(max_attempts=3),
            sleep=cancel_during_sleep,
        )

        with self.assertRaises(AgentCancelledError):
            agent.run("上海天气如何？", cancellation_token=token)

        self.assertEqual(1, len(weather.calls))


if __name__ == "__main__":
    unittest.main()
