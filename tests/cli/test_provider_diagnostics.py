from desktop_fixture import desktop
import pytest

NAMES = {"deepchat": "DeepChat", "cherry": "Cherry Studio", "minimax": "MiniMax Code"}


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
@pytest.mark.parametrize("state", ["directory", "unreadable"])
def test_unusable_desktop_source_has_provider_diagnostic(tmp_path, monkeypatch, provider, state):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    cli.source.unlink()
    if state == "directory":
        cli.source.mkdir()
        reason = f"{NAMES[provider]} session source is missing."
    else:
        cli.source.write_bytes(b"synthetic unreadable database, not a SQLCipher fixture")
        reason = (
            "DeepChat database is encrypted or is not a readable SQLite database."
            if provider == "deepchat"
            else "file is not a database"
        )
    before = cli.fixtures.source_manifest(cli.root)
    result = cli.run(
        "rust", f"{provider}://{identity}", "--format", "print,json,md", "--output", "exports", "--lang", "en"
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr == f"⚠️  {NAMES[provider]} session lookup failed: {reason}\n"
    assert result.stdout.startswith("Diagnostic\nSummary: No matching session found.\n")
    listing = cli.run("rust", "--list", "-d", "36500", "-q", f"provider:{provider}", "--lang", "en")
    assert listing.returncode == 0, listing.stdout + listing.stderr
    assert "Summary: No usable provider within the query scope." in listing.stdout
    assert listing.stderr.startswith(f"⚠️  {NAMES[provider]} provider operation failed: ")
    assert listing.stderr.endswith(f"{reason}\n")
    assert not (cli.root / "exports").exists()
    assert cli.fixtures.source_manifest(cli.root) == before
