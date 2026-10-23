import unittest

from agent_lab import (
    Agent,
    FinalAnswer,
    RetryPolicy,
    ToolCall,
    ToolConfirmationRejectedError,
    ToolConfirmationRequiredError,
    ToolErrorKind,
    ToolPermission,
    ToolPermissionDeniedError,
    ToolResult,
)
from agent_lab.testing import RecordingTool, ScriptedModel, ScriptedTool


def temporary_failure() -> ToolResult:
    return ToolResult.failure(
        ToolErrorKind.EXECUTION_ERROR,
        "temporary failure",
        retryable=True,
    )


class ToolPermissionTests(unittest.TestCase):
    def test_read_tool_runs_without_confirmation_or_idempotency_key(self) -> None:
        model = ScriptedModel(
            [ToolCall("weather", {"city": "Shanghai"}), FinalAnswer("sunny")]
        )
        weather = RecordingTool("weather", "sunny")

        def unexpected_confirmation(request) -> bool:
            self.fail("read tools must not request confirmation")

        def unexpected_key() -> str:
            self.fail("read tools must not allocate idempotency keys")

        Agent(
            model,
            [weather],
            confirmation_handler=unexpected_confirmation,
            idempotency_key_factory=unexpected_key,
        ).run("上海天气如何？")

        self.assertEqual(1, len(weather.calls))
        self.assertIsNone(weather.contexts[0].idempotency_key)
        self.assertEqual(1, weather.contexts[0].attempt)

    def test_write_tool_is_denied_without_static_permission(self) -> None:
        model = ScriptedModel([ToolCall("send_email", {"body": "hello"})])
        sender = RecordingTool(
            "send_email",
            "sent",
            permission=ToolPermission.WRITE,
            supports_idempotency=True,
        )

        with self.assertRaises(ToolPermissionDeniedError):
            Agent(model, [sender]).run("发送邮件")

        self.assertEqual([], sender.calls)

    def test_allowed_write_requires_a_confirmation_handler(self) -> None:
        model = ScriptedModel([ToolCall("send_email", {"body": "hello"})])
        sender = RecordingTool(
            "send_email",
            "sent",
            permission=ToolPermission.WRITE,
            supports_idempotency=True,
        )

        with self.assertRaises(ToolConfirmationRequiredError):
            Agent(
                model,
                [sender],
                allowed_permissions={ToolPermission.READ, ToolPermission.WRITE},
            ).run("发送邮件")

        self.assertEqual([], sender.calls)

    def test_rejected_write_is_not_executed(self) -> None:
        model = ScriptedModel([ToolCall("send_email", {"body": "hello"})])
        sender = RecordingTool(
            "send_email",
            "sent",
            permission=ToolPermission.WRITE,
            supports_idempotency=True,
        )
        requests = []

        def reject(request) -> bool:
            requests.append(request)
            return False

        with self.assertRaises(ToolConfirmationRejectedError):
            Agent(
                model,
                [sender],
                allowed_permissions={ToolPermission.READ, ToolPermission.WRITE},
                confirmation_handler=reject,
                idempotency_key_factory=lambda: "email-123",
            ).run("发送邮件")

        self.assertEqual([], sender.calls)
        self.assertEqual(1, len(requests))
        self.assertEqual("email-123", requests[0].idempotency_key)

    def test_confirmed_write_receives_host_owned_context(self) -> None:
        model = ScriptedModel(
            [ToolCall("send_email", {"body": "hello"}), FinalAnswer("已发送")]
        )
        sender = RecordingTool(
            "send_email",
            "sent",
            permission=ToolPermission.WRITE,
            supports_idempotency=True,
        )
        requests = []

        def approve(request) -> bool:
            requests.append(request)
            return True

        result = Agent(
            model,
            [sender],
            allowed_permissions={ToolPermission.READ, ToolPermission.WRITE},
            confirmation_handler=approve,
            idempotency_key_factory=lambda: "email-123",
        ).run("发送邮件")

        self.assertEqual("已发送", result.answer)
        self.assertEqual(1, len(requests))
        self.assertEqual("send_email", requests[0].tool_name)
        self.assertEqual({"body": "hello"}, requests[0].arguments)
        self.assertEqual("email-123", requests[0].idempotency_key)
        self.assertEqual("email-123", sender.contexts[0].idempotency_key)
        self.assertEqual(1, sender.contexts[0].attempt)

    def test_idempotent_write_reuses_one_key_across_retries(self) -> None:
        model = ScriptedModel(
            [ToolCall("send_email", {"body": "hello"}), FinalAnswer("已发送")]
        )
        sender = ScriptedTool(
            "send_email",
            [temporary_failure(), ToolResult.success("sent")],
            permission=ToolPermission.WRITE,
            supports_idempotency=True,
        )
        confirmations = []

        def approve(request) -> bool:
            confirmations.append(request)
            return True

        result = Agent(
            model,
            [sender],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay=0),
            allowed_permissions={ToolPermission.READ, ToolPermission.WRITE},
            confirmation_handler=approve,
            idempotency_key_factory=lambda: "email-123",
        ).run("发送邮件")

        self.assertEqual("已发送", result.answer)
        self.assertEqual(2, len(sender.calls))
        self.assertEqual(1, len(confirmations))
        self.assertEqual([1, 2], [context.attempt for context in sender.contexts])
        self.assertEqual(
            ["email-123", "email-123"],
            [context.idempotency_key for context in sender.contexts],
        )

    def test_non_idempotent_write_is_never_automatically_retried(self) -> None:
        model = ScriptedModel(
            [
                ToolCall("append_file", {"text": "hello"}),
                FinalAnswer("写入状态未知"),
            ]
        )
        writer = ScriptedTool(
            "append_file",
            [temporary_failure()],
            permission=ToolPermission.WRITE,
            supports_idempotency=False,
        )

        Agent(
            model,
            [writer],
            retry_policy=RetryPolicy(max_attempts=3, initial_delay=0),
            allowed_permissions={ToolPermission.READ, ToolPermission.WRITE},
            confirmation_handler=lambda request: True,
            idempotency_key_factory=lambda: "write-123",
        ).run("追加文件")

        self.assertEqual(1, len(writer.calls))

    def test_invalid_write_arguments_do_not_request_confirmation(self) -> None:
        parameters = {
            "type": "object",
            "properties": {"body": {"type": "string"}},
            "required": ["body"],
            "additionalProperties": False,
        }
        model = ScriptedModel(
            [ToolCall("send_email", {"body": 42}), FinalAnswer("参数错误")]
        )
        sender = RecordingTool(
            "send_email",
            "sent",
            parameters=parameters,
            permission=ToolPermission.WRITE,
            supports_idempotency=True,
        )

        def unexpected_confirmation(request) -> bool:
            self.fail("invalid arguments must not request confirmation")

        Agent(
            model,
            [sender],
            allowed_permissions={ToolPermission.READ, ToolPermission.WRITE},
            confirmation_handler=unexpected_confirmation,
        ).run("发送邮件")

        self.assertEqual([], sender.calls)


if __name__ == "__main__":
    unittest.main()
