import re

from cli_fixture import CliFixture, make_cli
import pytest

LATER_PROVIDERS = re.compile(
    r"kimi[-_]code|qoder|\bomp\b|oh-my-pi|grok|gemini[-_ ]cli|antigravity|\bdroid\b", re.IGNORECASE
)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    return make_cli(tmp_path, monkeypatch)


@pytest.fixture(autouse=True)
def hide_later_providers(request, monkeypatch):
    """v0.15.9 predates these providers, so differential runs drop the Rust lines that enumerate them."""
    if request.node.get_closest_marker("differential") is None:
        return
    run = CliFixture.run

    def hide(text):
        # Session groups only appear when a test creates sources for the provider.
        return "".join(
            line
            for line in text.splitlines(keepends=True)
            if line.startswith("📁 ") or not LATER_PROVIDERS.search(line)
        )

    def legacy_run(self, candidate, *args, **kwargs):
        result = run(self, candidate, *args, **kwargs)
        if candidate == "rust":
            result.stdout, result.stderr = hide(result.stdout), hide(result.stderr)
        return result

    monkeypatch.setattr(CliFixture, "run", legacy_run)
