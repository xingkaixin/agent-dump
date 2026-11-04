"""Recoverable record warnings keep healthy content without changing source or export bytes."""

import json

from cli_fixture import IDENTITY, header, message


def test_damaged_jsonl_records_keep_healthy_content(cli):
    cli.write([header(), message("user", "Keep")])
    source = cli.source
    original = source.read_bytes()
    source.write_bytes(
        original
        + b'\ninvalid\n\xff\n[]\n1\n"text"\nnull\ntrue\n'
        + original.splitlines(keepends=True)[-1]
        + b'{"partial":'
    )
    first_bad_line = original.count(b"\n") + 2
    before = cli.fixtures.source_manifest(cli.root)
    args = (f"codex://{IDENTITY}", "--format", "json,md,raw,print", "--output", "exports", "--lang", "en")
    result = cli.run(*args)
    assert result.returncode == 0, result.stdout + result.stderr
    warnings = result.stderr.splitlines()
    assert len(warnings) == 1
    samples = ", ".join(str(line) for line in range(first_bad_line, first_bad_line + 5))
    assert samples in warnings[0] and str(source) in warnings[0]
    assert next((cli.root / "exports").rglob("*.jsonl")).read_bytes() == source.read_bytes()
    payload = json.loads(next((cli.root / "exports").rglob("*.json")).read_text())
    assert payload["stats"]["message_count"] == 2
    assert cli.fixtures.source_manifest(cli.root) == before
