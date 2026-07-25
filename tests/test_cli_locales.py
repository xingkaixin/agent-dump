"""端到端验证 CLI 在两个 locale 下的输出（AD-137）。

detect_language（i18n.py:660-674）对任何非 zh 的机器 locale 返回 "en"，所以 en 是多数
用户实际拿到的路径——而在此之前，conftest 的 autouse fixture 把所有测试恒定为 zh，
`--lang en` 在 tests/ 中出现 0 次，这条路径从未被任何工作流验证过。

断言一律经 expect() 按当前 locale 解析，不写死任何一种语言的字面量；这样 i18n 文案
改写时这些测试不需要跟着改。
"""

from locale_helpers import ALL_LANGUAGES, Keys, expect, expect_contains
import pytest
from test_integration_cli import read_only_file, run_cli

from agent_dump.i18n import i18n


@pytest.fixture(params=ALL_LANGUAGES)
def language(request, use_language):
    """把测试分别跑在 zh 与 en 两个 locale 下。"""
    use_language(request.param)
    return request.param


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

        monkeypatch.setattr(ClaudeCodeAgent, "is_available", lambda self: True)
        monkeypatch.setattr(
            ClaudeCodeAgent, "get_sessions", lambda self, days=7: (_ for _ in ()).throw(ValueError("bad row"))
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
