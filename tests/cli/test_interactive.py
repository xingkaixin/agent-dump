"""Non-TTY selection remains usable in pipelines without a terminal UI."""

import json
import shutil

import pytest
from test_config_shortcuts import config_path


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "selection", ["all\n", "1\n", "2,1,2\n", "0,1,99\n", "q\n", "\n", "bad\n", "", "１\n", "1_0\n"]
)
@pytest.mark.parametrize("metadata", [True, False])
def test_session_selection(cli, lang, selection, metadata):
    args = ["--interactive", "-q", "provider:codex", "-d", "36500", "--output", "exports", "--lang", lang]
    if not metadata:
        args += ["--no-metadata-summary"]
    results = []
    outputs = []
    for candidate in ["python", "rust"]:
        shutil.rmtree(cli.root / "exports", ignore_errors=True)
        result = cli.run(candidate, *args, stdin=selection)
        results.append((result.returncode, result.stdout, result.stderr))
        outputs.append({p.name: json.loads(p.read_text()) for p in (cli.root / "exports").rglob("*.json")})
    assert outputs[0] == outputs[1]
    assert results[0] == results[1]


@pytest.mark.parametrize("selection", ["1\nall\n", "2\n1\n", "0\n", "q\n", "", "99\n"])
def test_provider_selection(cli, selection):
    results = []
    for candidate in ["python", "rust"]:
        result = cli.run(
            candidate, "--interactive", "-d", "36500", "--lang", "en", "--output", "exports", stdin=selection
        )
        results.append((result.returncode, result.stdout, result.stderr))
    assert results[0] == results[1]


@pytest.mark.parametrize("formats", ["json", "md", "raw", "json,md,raw", "print"])
@pytest.mark.parametrize("explicit", [True, False])
def test_batch_formats_and_default_paths(cli, formats, explicit):
    config_path(cli).write_text('[export]\noutput="configured"\n')
    args = ["--interactive", "-q", "provider:codex", "-d", "36500", "--format", formats, "--lang", "en"]
    if explicit:
        args += ["--output", "exports"]
    results = []
    files = []
    for candidate in ["python", "rust"]:
        for directory in ["exports", "configured", "sessions"]:
            shutil.rmtree(cli.root / directory, ignore_errors=True)
        result = cli.run(candidate, *args, stdin="all\n")
        results.append((result.returncode, result.stdout, result.stderr))
        files.append(
            {
                str(p.relative_to(cli.root)): json.loads(p.read_text()) if p.suffix == ".json" else p.read_bytes()
                for directory in ["exports", "configured", "sessions"]
                for p in (cli.root / directory).rglob("*")
                if p.is_file()
            }
        )
    assert files[0] == files[1]
    assert results[0] == results[1]
