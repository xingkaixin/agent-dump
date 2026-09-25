"""The migration benchmark must reject shortcuts and keep Provider sources isolated."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "benchmark_cli.py"


@pytest.fixture
def benchmark(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("benchmark_cli")


def test_fixture_is_deterministic_and_does_not_inherit_provider_or_api_environment(tmp_path, monkeypatch, benchmark):
    fixtures = importlib.import_module("benchmark_fixtures")
    monkeypatch.setenv("OPENCODE_DB", str(tmp_path / "outside.db"))
    monkeypatch.setenv("MAVIS_DATA_DIR", str(tmp_path / "outside"))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-the-benchmark")
    first = tmp_path / "first"
    second = tmp_path / "second"
    environment = fixtures.create_fixture(first, fixtures.PROFILES["smoke"])
    fixtures.create_fixture(second, fixtures.PROFILES["smoke"])

    assert fixtures.source_manifest(first) == fixtures.source_manifest(second)
    assert "OPENAI_API_KEY" not in environment
    for name in ("HOME", "CODEX_HOME", "MAVIS_DATA_DIR", "OPENCODE_DB", "XDG_CACHE_HOME", "APPDATA"):
        assert Path(environment[name]).is_relative_to(first)
    assert not (tmp_path / "outside.db").exists()


def test_rust_cli_passes_every_smoke_workload_and_comparison_rejects_invalid_results(tmp_path, benchmark):
    report_path = tmp_path / "result.json"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            "--profile",
            "smoke",
            "--repeats",
            "1",
            "--warmups",
            "0",
            "--output",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(report_path.read_text())
    assert len(report["cases"]) == 17
    assert all(case["validation"] and case["samples"][0]["exit_code"] == 0 for case in report["cases"])
    assert all(row["wall_speedup"] == 1 for row in benchmark.compare_reports(report, report))

    changed = deepcopy(report)
    changed["cases"][2]["validation"]["sessions"] -= 1
    with pytest.raises(ValueError, match="validation differs"):
        benchmark.compare_reports(report, changed)
    changed = deepcopy(report)
    changed["source_manifest"]["sha256"] = "different-fixture"
    with pytest.raises(ValueError, match="different source_manifest"):
        benchmark.compare_reports(report, changed)
    changed = deepcopy(report)
    changed["cases"].pop()
    with pytest.raises(ValueError, match="different case sets"):
        benchmark.compare_reports(report, changed)


@pytest.mark.parametrize("behavior", ["wrong-result", "failure", "source-write"])
def test_invalid_cli_cannot_produce_a_successful_report(tmp_path, behavior):
    fake = tmp_path / "candidate.py"
    if behavior == "source-write":
        source = (
            "import os\nfrom pathlib import Path\n"
            "(Path(os.environ['CODEX_HOME']) / 'unexpected').write_text('changed')\n"
            "print('agent-dump 0.15.9')\n"
        )
    elif behavior == "failure":
        source = "raise SystemExit(3)\n"
    else:
        source = "print('fast but incorrect')\n"
    fake.write_text(source)
    report_path = tmp_path / "result.json"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(SCRIPT),
            "--profile",
            "smoke",
            "--repeats",
            "1",
            "--warmups",
            "0",
            "--case",
            "startup-version",
            "--command",
            shlex.join([sys.executable, str(fake)]),
            "--output",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert not report_path.exists()
    if behavior == "source-write":
        assert "modified Provider sources" in result.stderr


def test_collector_timeout_does_not_write_a_measurement(tmp_path):
    metrics = tmp_path / "metrics.json"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmark_process.py"),
            "--metrics",
            str(metrics),
            "--timeout",
            "0.05",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(10)",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "exceeded" in result.stderr
    assert not metrics.exists()


def test_success_exit_cannot_hide_missing_sessions_or_truncated_exports(tmp_path, benchmark):
    fixtures = importlib.import_module("benchmark_fixtures")
    checks = importlib.import_module("benchmark_cases")
    profile = fixtures.PROFILES["smoke"]
    with pytest.raises(ValueError, match="session identities"):
        checks.validate(checks.Case("list", (), "list"), profile, tmp_path, "", 0)

    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / "session.json").write_text(
        json.dumps({"id": fixtures.codex_id(profile.sessions_per_provider), "messages": []})
    )
    with pytest.raises(ValueError, match="exported messages differ"):
        checks.check_exports(checks.Case("export", (), "export-large"), profile, tmp_path)
