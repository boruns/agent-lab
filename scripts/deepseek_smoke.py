"""Explicit, paid DeepSeek smoke test; never run from the unit test suite."""

from agent_lab import FinalAnswer, Message
from agent_lab.deepseek import DeepSeekSettings, build_deepseek_transport
from agent_lab.providers import DeepSeekResponsesAdapter


def main() -> None:
    records = []
    settings = DeepSeekSettings.from_env()
    transport = build_deepseek_transport(settings, record_call=records.append)
    model = DeepSeekResponsesAdapter(settings.model, transport)

    decision = model.decide(
        [Message(role="user", content="Reply with exactly: agent-lab-ok")],
        [],
    )
    if not isinstance(decision, FinalAnswer):
        raise TypeError(f"Unexpected decision: {type(decision).__name__}")

    print(decision.content)
    if records:
        print(records[-1])


if __name__ == "__main__":
    main()
