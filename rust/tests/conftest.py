from cli_fixture import make_cli
import pytest


@pytest.fixture
def cli(tmp_path, monkeypatch):
    return make_cli(tmp_path, monkeypatch)
