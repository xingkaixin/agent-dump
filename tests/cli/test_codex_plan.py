"""Codex plan approval across sub-agent notifications that arrive before the reply."""

import json

from cli_fixture import IDENTITY, header, message
import pytest


@pytest.mark.parametrize(
    "reference,approval",
    [("agent_id", "PLEASE IMPLEMENT THIS PLAN:\nStep 1"), ("agent_path", "Implement the plan.")],
)
def test_notification_does_not_consume_the_pending_plan(cli, reference, approval):
    notification = json.dumps({reference: "child", "status": {"completed": "Child done"}})
    cli.write(
        [
            header(),
            message("user", "Make a plan"),
            message("assistant", "<proposed_plan>\nStep 1\n</proposed_plan>"),
            message("user", f"<subagent_notification>\n{notification}\n</subagent_notification>"),
            message("user", approval),
        ]
    )
    result = cli.run("rust", f"codex://{IDENTITY}", "--format", "json", "--output", "exports")
    assert result.returncode == 0, result.stderr
    messages = json.loads((cli.root / "exports" / "codex" / f"{IDENTITY}.json").read_text())["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "assistant"]
    plan = messages[1]["parts"][0]
    assert (plan["type"], plan["approval_status"], plan["output"]) == ("plan", "success", None)
    assert messages[2]["subagent_id"] == "child"
    assert messages[2]["parts"][0]["text"] == "Child done"
