"""端到端验证 CLI 在两个 locale 下的输出（AD-137）。

detect_language（i18n.py:660-674）对任何非 zh 的机器 locale 返回 "en"，所以 en 是多数
用户实际拿到的路径——而在此之前，conftest 的 autouse fixture 把所有测试恒定为 zh，
`--lang en` 在 tests/ 中出现 0 次，这条路径从未被任何工作流验证过。

断言一律经 expect() 按当前 locale 解析，不写死任何一种语言的字面量；这样 i18n 文案
改写时这些测试不需要跟着改。
"""

from pathlib import Path
from unittest import mock

from locale_helpers import ALL_LANGUAGES, Keys, expect, expect_contains
import pytest
from test_integration_cli import read_only_file, run_cli

from agent_dump.cli import main
from agent_dump.i18n import i18n


def _session(session_id: str, source_path: Path):
    """构造一个真实 Session；export_raw_session 会用 id 拼输出路径，Mock 不行。"""
    from datetime import datetime, timezone

    from agent_dump.agents.base import Session

    now = datetime(2026, 7, 20, tzinfo=timezone.utc)
    return Session(id=session_id, title="t", created_at=now, updated_at=now, source_path=source_path, metadata={})


@pytest.fixture(params=ALL_LANGUAGES)
def language(request, use_language):
    """把测试分别跑在 zh 与 en 两个 locale 下。"""
    use_language(request.param)
    return request.param


class TestHelpIsLocalized:
    def test_page_size_is_described_as_ignored_compatibility_input(self, language, capsys):
        with mock.patch("sys.argv", ["agent-dump", "--lang", language, "--help"]), pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 0
        output = capsys.readouterr().out
        assert expect(Keys.CLI_PAGE_SIZE_HELP) in output


class TestListModeIsLocalized:
    def test_header_and_session_are_shown(self, language, codex_session_tree, capsys):
        exit_code = run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert expect_contains(captured.out, Keys.LIST_HEADER, days=36500)
        assert codex_session_tree["title"] in captured.out

    def test_empty_window_reports_no_sessions(self, language, codex_session_tree, capsys):
        """会话存在但落在 -d 窗口之外。"""
        exit_code = run_cli("--list", "-d", "1")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert expect_contains(captured.out, Keys.NO_SESSIONS_IN_DAYS, days=1)

    def test_interactive_hint_is_localized(self, language, codex_session_tree, capsys):
        run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert expect_contains(captured.out, Keys.HINT_INTERACTIVE)


class TestQueryModeIsLocalized:
    def test_filtered_header_carries_the_query(self, language, codex_session_tree, capsys):
        exit_code = run_cli("--list", "-q", "登录超时", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert expect_contains(captured.out, Keys.LIST_HEADER_FILTERED, days=36500, query="登录超时")

    def test_keyword_miss_reports_an_empty_window(self, language, codex_session_tree, capsys):
        exit_code = run_cli("--list", "-q", "zzznosuchtokenzzz", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert expect_contains(captured.out, Keys.NO_SESSIONS_IN_DAYS, days=36500)


class TestExportIsLocalized:
    def test_export_succeeds_and_reports_in_the_active_locale(self, language, codex_session_tree, tmp_path, capsys):
        out = tmp_path / f"out-{language}"

        exit_code = run_cli(f"codex://{codex_session_tree['session_id']}", "-format", "json", "-output", str(out))
        captured = capsys.readouterr()

        assert exit_code == 0
        assert read_only_file(out, ".json").is_file()
        assert captured.out.strip(), "导出应给出用户可见的反馈"


class TestLangFlagOverridesDetection:
    """`--lang` 是 AD-138 那批未翻译诊断的官方逃逸口，必须真的生效。"""

    @pytest.mark.parametrize("lang", ALL_LANGUAGES)
    def test_flag_selects_the_catalog(self, lang, codex_session_tree, capsys):
        run_cli("--list", "-d", "36500", "--lang", lang)
        captured = capsys.readouterr()

        assert i18n.lang == lang
        assert i18n.t(Keys.LIST_HEADER, days=36500).strip() in captured.out

    def test_the_two_catalogs_actually_differ(self, codex_session_tree, use_language):
        """否则上面那些 expect() 断言在两份目录退化成同一文案时也会通过。"""
        use_language("zh")
        zh_header = expect(Keys.LIST_HEADER, days=7)
        use_language("en")
        en_header = expect(Keys.LIST_HEADER, days=7)

        assert zh_header != en_header


class TestDiagnosticsAreLocalized:
    """AD-138：诊断是工具的主要失败面，此前整块是硬编码中文。"""

    def test_no_local_session_data(self, language, isolated_provider_home, capsys):
        run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert expect_contains(captured.out, Keys.DIAGNOSTIC_HEADER)
        assert expect_contains(captured.out, Keys.DIAG_NO_LOCAL_SESSIONS)
        assert expect_contains(captured.out, Keys.DIAG_STEP_CHECK_AGENT_DATA)
        assert expect_contains(captured.out, Keys.DIAGNOSTIC_SEARCHED_ROOTS)

    def test_unparseable_uri(self, language, codex_session_tree, capsys):
        exit_code = run_cli("not-a-supported-uri")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert expect_contains(captured.out, Keys.DIAG_URI_INVALID)
        assert expect_contains(captured.out, Keys.DIAG_URI_UNPARSEABLE)

    def test_unknown_session_id(self, language, codex_session_tree, capsys):
        exit_code = run_cli("codex://no-such-session-id")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert expect_contains(captured.out, Keys.DIAG_SESSION_NOT_FOUND)
        assert expect_contains(captured.out, Keys.DIAG_URI_SCANNED_NO_MATCH)

    def test_unexpected_failure_wrapper(self, language, codex_session_tree, monkeypatch, capsys):
        monkeypatch.setattr("agent_dump.cli._run", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        exit_code = run_cli("--list")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert expect_contains(captured.out, Keys.DIAG_UNEXPECTED_FAILURE)
        assert expect_contains(captured.out, Keys.DIAG_STEP_RETRY_ONCE)


class TestWarningsAreLocalized:
    def test_provider_failure_warning(self, language, codex_session_tree, monkeypatch, capsys):
        from agent_dump.agents.claudecode import ClaudeCodeAgent

        monkeypatch.setattr(
            ClaudeCodeAgent,
            "_get_available_sessions",
            lambda self, days=7: (_ for _ in ()).throw(ValueError("bad row")),
        )

        run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert expect_contains(
            captured.err,
            Keys.WARN_PROVIDER_OPERATION_FAILED,
            agent="Claude Code",
            error_type="ValueError",
            error="bad row",
        )


class TestProviderDiagnosticsAreLocalized:
    """AD-146：provider 专属的 next_steps 只在该 provider 数据缺失时出现。"""

    def test_missing_raw_source_next_steps(self, language, codex_session_tree, tmp_path):
        """源文件缺失时 base.py 的 source_missing 诊断。

        不走 CLI：删掉唯一的会话文件会让整个 provider 变为不可用，拿到的是
        「无本地会话数据」而不是这一条。
        """
        from agent_dump.agents.codex import CodexAgent
        from agent_dump.diagnostics import DiagnosticError

        session = _session("s1", tmp_path / "gone.jsonl")
        with pytest.raises(DiagnosticError) as excinfo:
            CodexAgent().export_raw_session(session, tmp_path / "out")

        assert expect(Keys.DIAG_STEP_RAW_SOURCE_LOCAL) in excinfo.value.next_steps
        assert expect(Keys.DIAG_STEP_LIST_TO_CHECK_VISIBLE) in excinfo.value.next_steps

    def test_cursor_unsupported_format_next_steps(self, language, codex_session_tree, capsys):
        """Cursor 的 raw 导出能力缺失诊断来自 cursor.py。"""
        from agent_dump.agents.cursor import CursorAgent
        from agent_dump.diagnostics import DiagnosticError

        agent = CursorAgent()
        with pytest.raises(DiagnosticError) as excinfo:
            agent.export_raw_session(_session("x", Path("/tmp/x.db")), Path("/tmp"))

        assert expect(Keys.DIAG_STEP_USE_JSON_OR_PRINT) in excinfo.value.next_steps
        assert expect(Keys.DIAG_STEP_CURSOR_INSPECT_SQLITE) in excinfo.value.next_steps

    def test_opencode_missing_database_next_steps(self, language, isolated_provider_home, capsys):
        from agent_dump.agents.opencode import OpenCodeAgent
        from agent_dump.diagnostics import DiagnosticError

        agent = OpenCodeAgent()
        with pytest.raises(DiagnosticError) as excinfo:
            agent._connect_db()

        assert expect(Keys.DIAG_STEP_OPENCODE_DB_EXISTS) in excinfo.value.next_steps
        assert expect(Keys.DIAG_STEP_OPENCODE_DEV_DB) in excinfo.value.next_steps

    def test_zcode_missing_database_next_steps(self, language, isolated_provider_home):
        from agent_dump.agents.zcode import ZCodeAgent

        error = ZCodeAgent()._missing_database_error(None)

        assert expect(Keys.DIAG_STEP_ZCODE_DB_EXISTS) in error.next_steps
        assert expect(Keys.DIAG_STEP_ZCODE_NO_LINUX) in error.next_steps

    def test_kimi_missing_jsonl_next_steps(self, language, isolated_provider_home):
        from agent_dump.agents.kimi import KimiAgent
        from agent_dump.diagnostics import DiagnosticError

        session = _session("s1", Path(str(isolated_provider_home)) / "missing")
        with pytest.raises(DiagnosticError) as excinfo:
            KimiAgent().export_raw_session(session, Path(str(isolated_provider_home)) / "out")

        assert expect(Keys.DIAG_STEP_KIMI_NEEDS_JSONL) in excinfo.value.next_steps
        assert expect(Keys.DIAG_STEP_READABLE_EXPORT_INSTEAD) in excinfo.value.next_steps
