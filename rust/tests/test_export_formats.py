"""Export boundaries: byte preservation, partial success and source protection."""

import shutil

from cli_fixture import IDENTITY, header, message
import pytest


def test_raw_export_preserves_invalid_records_and_partial_tail(cli):
    cli.write([header(), message("user", "Keep")], suffix=b'not-json\n\xff\n{"partial":')
    cli.parity(f"codex://{IDENTITY}", "--format", "raw", "--output", "exports", "--lang", "en", formats=("raw",))
    assert (cli.root / "exports" / "codex" / f"{IDENTITY}.raw.jsonl").read_bytes() == cli.source.read_bytes()


@pytest.mark.parametrize("blocked", [(".json",), (".json", ".md", ".raw.jsonl")])
def test_file_export_failures_do_not_stop_other_formats(cli, blocked):
    before = cli.fixtures.source_manifest(cli.root)
    artifacts = []
    for candidate in ("python", "rust"):
        directory = cli.root / "exports" / "codex"
        shutil.rmtree(directory.parent, ignore_errors=True)
        directory.mkdir(parents=True)
        for suffix in blocked:
            (directory / f"{IDENTITY}{suffix}").mkdir()
        result = cli.run(candidate, f"codex://{IDENTITY}", "--format", "json,md,raw", "--output", "exports")
        assert result.returncode == (1 if len(blocked) == 3 else 0), result.stdout + result.stderr
        assert "Error:" in result.stderr if candidate == "rust" else "Diagnostic\n" in result.stdout
        files = sorted(path for path in directory.iterdir() if path.is_file())
        assert len(files) == 3 - len(blocked)
        artifacts.append({path.name: path.read_bytes() for path in files})
        assert len(list(directory.iterdir())) == 3
        assert cli.fixtures.source_manifest(cli.root) == before
    assert artifacts[0] == artifacts[1]


@pytest.mark.parametrize("output_format", ["markdown", "raw"])
def test_new_export_formats_cannot_write_into_source(cli, output_format):
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(
        "rust", f"codex://{IDENTITY}", "--format", output_format, "--output", str(cli.root / "sources" / "codex")
    )
    assert result.returncode == 1
    assert cli.fixtures.source_manifest(cli.root) == before
