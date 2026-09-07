"""Behavior shared by OpenCode-compatible SQLite providers."""

from dataclasses import replace
import json
import shutil
import sqlite3

import pytest

from agent_dump.agents.opencode import OpenCodeAgent
from agent_dump.agents.zcode import ZCodeAgent


@pytest.mark.parametrize("agent_type", [OpenCodeAgent, ZCodeAgent])
def test_read_and_export_use_session_source_without_discovery(agent_type, populated_db, tmp_path):
    discoverer = agent_type()
    discoverer.db_path = populated_db
    session = discoverer.get_sessions(days=None)[0]
    reader = agent_type()

    assert reader.get_session_data(session)["messages"][0]["parts"][0]["text"] == "Hello World"
    exported = reader.export_session(session, tmp_path / "exports")
    assert json.loads(exported.read_text(encoding="utf-8"))["messages"][0]["parts"][0]["text"] == "Hello World"
    assert reader.db_path is None

    other_db = tmp_path / "other.db"
    shutil.copyfile(populated_db, other_db)
    conn = sqlite3.connect(other_db)
    try:
        conn.execute("UPDATE part SET data = ?", (json.dumps({"type": "text", "text": "Other source"}),))
        conn.commit()
    finally:
        conn.close()
    reader.db_path = other_db

    assert reader.get_session_data(session)["messages"][0]["parts"][0]["text"] == "Hello World"
    with pytest.raises(FileNotFoundError):
        reader.get_session_data(replace(session, source_path=tmp_path / "missing.db"))
    assert not (tmp_path / "missing.db").exists()
