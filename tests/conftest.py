"""
测试配置和共享 fixtures
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from agent_dump.i18n import i18n


@pytest.fixture(autouse=True)
def isolated_search_index_cache(tmp_path_factory, monkeypatch):
    """所有测试的搜索索引写入临时目录，避免读写真实用户缓存并防止跨测试污染。"""
    cache_dir = tmp_path_factory.mktemp("xdg-cache")
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))


@pytest.fixture(autouse=True)
def set_language_zh(monkeypatch):
    # Force language to Chinese for all tests to match existing assertions
    # Patch detect_language to always return 'zh' so setup_i18n() in main() doesn't overwrite it to 'en'
    monkeypatch.setattr("agent_dump.i18n.I18n.detect_language", lambda self: "zh")

    # Also set initial state
    i18n.set_language("zh")
    yield
    # Reset to default (en) after test
    i18n.set_language("en")


@pytest.fixture
def isolated_provider_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把全部 provider 的路径发现指向临时 home，禁止触达真实用户会话目录。

    覆盖三条发现渠道：官方环境变量、Path.home() 派生的默认目录（HOME 生效于
    ProviderRoots、zcode、cursor 与 config.toml），以及 `data/<agent>` 这个相对
    CWD 的本地开发回退（靠 chdir 到空目录中和）。
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("CURSOR_DATA_PATH", str(home / "cursor-data"))
    for env_var in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "KIMI_SHARE_DIR", "PI_HOME", "LOCALAPPDATA", "APPDATA"):
        monkeypatch.delenv(env_var, raising=False)
    return home


def _codex_record(timestamp: str, payload: dict) -> str:
    return json.dumps({"type": "response_item", "timestamp": timestamp, "payload": payload})


@pytest.fixture
def codex_session_tree(isolated_provider_home: Path) -> dict[str, object]:
    """在临时 home 下写一个真实可解析的 Codex 会话文件。

    返回 session id、文件路径与预期正文片段，供集成测试断言真实产物内容。
    """
    session_id = "019c213e-c251-73a3-af66-0ec9d7cb9e29"
    sessions_dir = isolated_provider_home / ".codex" / "sessions" / "2026" / "07"
    sessions_dir.mkdir(parents=True)
    session_file = sessions_dir / f"rollout-2026-07-20T10-04-47-{session_id}.jsonl"

    created = datetime(2026, 7, 20, 10, 4, 47, tzinfo=timezone.utc)
    lines = [
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "timestamp": created.isoformat().replace("+00:00", "Z"),
                    "cwd": "/workspace/demo",
                    "cli_version": "1.2.3",
                    "model_provider": "openai",
                },
            }
        ),
        _codex_record(
            "2026-07-20T10:05:00Z",
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "帮我修复登录超时"}]},
        ),
        _codex_record(
            "2026-07-20T10:05:10Z",
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "先复现该超时"}]},
        ),
        _codex_record(
            "2026-07-20T10:05:20Z",
            {"type": "function_call", "name": "exec_command", "call_id": "call-1", "arguments": {"cmd": "just test"}},
        ),
        _codex_record(
            "2026-07-20T10:05:30Z",
            {"type": "function_call_output", "call_id": "call-1", "output": "3 passed"},
        ),
    ]
    session_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    index_file = isolated_provider_home / ".codex" / "session_index.jsonl"
    index_file.write_text(json.dumps({"id": session_id, "thread_name": "修复登录超时"}) + "\n", encoding="utf-8")

    return {
        "home": isolated_provider_home,
        "session_id": session_id,
        "session_file": session_file,
        "title": "修复登录超时",
        "user_text": "帮我修复登录超时",
        "assistant_text": "先复现该超时",
    }


@pytest.fixture
def mock_db_path(tmp_path: Path) -> Path:
    """创建模拟数据库文件"""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 创建 session 表
    cursor.execute("""
        CREATE TABLE session (
            id TEXT PRIMARY KEY,
            title TEXT,
            time_created INTEGER,
            time_updated INTEGER,
            slug TEXT,
            directory TEXT,
            version INTEGER,
            summary_files TEXT
        )
    """)

    # 创建 message 表
    cursor.execute("""
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            time_created INTEGER,
            data TEXT
        )
    """)

    # 创建 part 表
    cursor.execute("""
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT,
            time_created INTEGER,
            data TEXT
        )
    """)

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_session() -> dict:
    """返回示例会话数据"""
    return {
        "id": "test-session-001",
        "title": "测试会话标题",
        "time_created": 1704067200000,  # 2024-01-01 00:00:00 in ms
        "time_updated": 1704153600000,
        "slug": "test-session",
        "directory": "/test/dir",
        "version": 1,
        "summary_files": "file1.py,file2.py",
        "created_formatted": "2024-01-01 00:00:00",
    }


@pytest.fixture
def sample_sessions() -> list[dict]:
    """返回多个示例会话数据"""
    return [
        {
            "id": "session-001",
            "title": "会话 1",
            "time_created": 1704067200000,
            "time_updated": 1704153600000,
            "slug": "session-1",
            "directory": "/test/dir1",
            "version": 1,
            "summary_files": "file1.py",
            "created_formatted": "2024-01-01 00:00:00",
        },
        {
            "id": "session-002",
            "title": "会话 2",
            "time_created": 1703980800000,
            "time_updated": 1704067200000,
            "slug": "session-2",
            "directory": "/test/dir2",
            "version": 1,
            "summary_files": "file2.py",
            "created_formatted": "2023-12-31 00:00:00",
        },
    ]


@pytest.fixture
def populated_db(mock_db_path: Path) -> Path:
    """创建填充了数据的模拟数据库"""
    conn = sqlite3.connect(mock_db_path)
    cursor = conn.cursor()

    # 插入会话
    cursor.execute(
        """
        INSERT INTO session (id, title, time_created, time_updated, slug, directory, version, summary_files)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        ("session-001", "测试会话", 1704067200000, 1704153600000, "test", "/test", 1, "file.py"),
    )

    # 插入消息
    msg_data = {
        "role": "user",
        "agent": "claude",
        "mode": "chat",
        "modelID": "claude-3-opus",
        "providerID": "anthropic",
        "time": {"completed": 1704067300000},
        "tokens": {"input": 100, "output": 50},
        "cost": 0.001,
    }
    cursor.execute(
        """
        INSERT INTO message (id, session_id, time_created, data)
        VALUES (?, ?, ?, ?)
    """,
        ("msg-001", "session-001", 1704067200000, json.dumps(msg_data)),
    )

    # 插入 part
    part_data = {"type": "text", "text": "Hello World"}
    cursor.execute(
        """
        INSERT INTO part (id, message_id, time_created, data)
        VALUES (?, ?, ?, ?)
    """,
        ("part-001", "msg-001", 1704067200000, json.dumps(part_data)),
    )

    conn.commit()
    conn.close()
    return mock_db_path


@pytest.fixture
def two_provider_tree(codex_session_tree: dict[str, object]) -> dict[str, object]:
    """在 codex 之外再造一个可用的 Claude Code provider。

    很多分层/扫描次数的问题只在「有多个 provider 可选」时才出现——单 provider 会
    走自动选中分支，绕开 selector。
    """
    home = codex_session_tree["home"]
    assert isinstance(home, Path)
    project_dir = home / ".claude" / "projects" / "demo-project"
    project_dir.mkdir(parents=True)
    session_id = "claude-session-0001"
    (project_dir / f"{session_id}.jsonl").write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {
                    "type": "user",
                    "timestamp": "2026-07-20T11:00:00Z",
                    "cwd": "/workspace/demo",
                    "version": "1.0.0",
                    "message": {"role": "user", "content": "检查缓存失效"},
                },
                {
                    "type": "assistant",
                    "timestamp": "2026-07-20T11:00:10Z",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "先看 TTL 配置"}]},
                },
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return {**codex_session_tree, "claude_session_id": session_id}
