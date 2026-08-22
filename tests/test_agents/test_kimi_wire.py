import json
from pathlib import Path

from agent_dump.agents.kimi_wire import parse_kimi_wire


def write_wire(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_parse_kimi_wire_keeps_tool_owner_after_fallback_message(tmp_path: Path) -> None:
    wire_path = tmp_path / "wire.jsonl"
    write_wire(
        wire_path,
        [
            {
                "message": {
                    "type": "TurnBegin",
                    "payload": {"user_input": [{"text": "hello"}]},
                }
            },
            {
                "message": {
                    "type": "ContentPart",
                    "payload": {"type": "text", "text": "working"},
                }
            },
            {
                "message": {
                    "type": "ToolResult",
                    "payload": {"tool_call_id": "missing", "return_value": "orphan"},
                }
            },
            {
                "message": {
                    "type": "ToolCall",
                    "payload": {
                        "id": "read-1",
                        "function": {"name": "ReadFile", "arguments": "{}"},
                    },
                }
            },
            {
                "message": {
                    "type": "ToolResult",
                    "payload": {"tool_call_id": "read-1", "return_value": "contents"},
                }
            },
        ],
    )

    result = parse_kimi_wire(wire_path)

    assistant = result.messages[1]
    assert [part["type"] for part in assistant["parts"]] == ["text", "tool"]
    assert assistant["parts"][1]["state"]["output"][0]["text"] == "contents"
    assert result.messages[2]["role"] == "tool"


def test_parse_kimi_wire_returns_aggregate_invalid_record_diagnostic(tmp_path: Path) -> None:
    wire_path = tmp_path / "wire.jsonl"
    wire_path.write_bytes(
        b'{"message": "invalid-shape"}\n'
        b"not-json\n"
        b'{"message": {"type": "TurnBegin", "payload": {"user_input": [{"text": "ok"}]}}}\n'
    )

    result = parse_kimi_wire(wire_path)

    assert [message["id"] for message in result.messages] == ["wire-3"]
    assert result.diagnostic is not None
    assert result.diagnostic.fields["count"] == 1
    assert result.diagnostic.fields["lines"] == "2"
