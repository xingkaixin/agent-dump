"""Provider source recovery preserves readable records and raw bytes."""

import json
import shutil

from cli_fixture import IDENTITY
import pytest
from test_claude import create as create_claude, event
from test_kimi import create as create_kimi
from test_pi import create as create_pi, message


@pytest.mark.parametrize("provider,scheme", [("claudecode", "claude"), ("kimi", "kimi"), ("pi", "pi")])
def test_malformed_lines_keep_readable_messages_and_raw_export(cli, provider, scheme):
    if provider == "claudecode":
        source = create_claude(cli, [event("user", "Keep")])
    elif provider == "kimi":
        source = create_kimi(cli, context=[{"role": "user", "content": "Keep"}]) / "context.jsonl"
    else:
        source = create_pi(cli, [message("user", "Keep")])
    source.write_bytes(source.read_bytes() + b'broken\n\xff\n[]\n{"partial":')
    before = cli.fixtures.source_manifest(cli.root)
    artifacts = []
    for candidate in ("python", "rust"):
        output = cli.root / "exports"
        shutil.rmtree(output, ignore_errors=True)
        result = cli.run(
            candidate, f"{scheme}://{IDENTITY}", "--format", "json,md,raw", "--output", "exports", "--lang", "en"
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "skipped 3" in result.stderr.lower(), result.stdout + result.stderr
        files = sorted(output.rglob("*.*"))
        assert len(files) == 3
        artifacts.append(
            {path.name: json.loads(path.read_text()) if path.suffix == ".json" else path.read_bytes() for path in files}
        )
        assert next(output.rglob("*.jsonl")).read_bytes() == source.read_bytes()
        assert cli.fixtures.source_manifest(cli.root) == before
    assert artifacts[0] == artifacts[1]
