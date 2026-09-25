from desktop_fixture import desktop
import pytest


@pytest.mark.parametrize("provider", ["deepchat", "cherry", "minimax"])
@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize("state", ["directory", "unreadable"])
def test_unusable_desktop_source_has_provider_diagnostic(tmp_path, monkeypatch, provider, lang, state):
    cli, identity = desktop(tmp_path, monkeypatch, provider)
    cli.source.unlink()
    if state == "directory":
        cli.source.mkdir()
    else:
        cli.source.write_bytes(b"synthetic unreadable database, not a SQLCipher fixture")
    cli.parity(
        f"{provider}://{identity}", "--format", "print,json,md", "--output", "exports", "--lang", lang, exit_code=1
    )
    cli.parity("--list", "-d", "36500", "-q", f"provider:{provider}", "--lang", lang)
    cli.parity("--list", "-d", "36500", "--lang", lang)
    assert not list((cli.root / "exports").rglob("*"))
