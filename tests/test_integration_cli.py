"""CLI 端到端集成测试。

与 test_cli.py 的分工：test_cli.py 用 mock 覆盖参数解析与模式分发，本文件不 mock
任何业务对象，走完整链路 argv → agent_registry → 真实 provider 文件 → 真实产物，
并断言磁盘上的实际内容与退出码。目的是覆盖两者之间的接缝：registry 接线、
export_paths 路径构造、rendering 的格式分发、退出码传播。

约定：只 mock sys.argv（main() 直接读它），其余一律真实执行。
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from agent_dump.cli import main


def run_cli(*argv: str) -> int:
    """以真实 argv 调用 main()，返回归一化后的退出码。"""
    with mock.patch("sys.argv", ["agent-dump", *argv]):
        result = main()
    return 0 if result is None else result


def read_only_file(directory: Path, suffix: str) -> Path:
    """取出目录下唯一一个指定后缀的产物，产物数量不为 1 时直接失败。"""
    matches = sorted(directory.rglob(f"*{suffix}"))
    assert len(matches) == 1, f"预期 {directory} 下恰好一个 {suffix} 产物，实际 {matches}"
    return matches[0]


class TestProviderIsolation:
    """先证明隔离本身有效，否则后续断言都可能来自真实用户数据。"""

    def test_only_fixture_provider_is_available(self, codex_session_tree):
        """临时 home 下只有被造出数据的 provider 可用，未触达真实用户目录。"""
        from agent_dump.scanner import AgentScanner

        available = sorted(agent.name for agent in AgentScanner().get_available_agents())

        assert available == ["codex"]


class TestListMode:
    def test_list_prints_session_title_from_real_file(self, codex_session_tree, capsys):
        """--list 经真实扫描输出会话标题，不写任何文件。"""
        exit_code = run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["title"] in captured.out
        assert codex_session_tree["session_id"] in captured.out
        assert not (Path.cwd() / "sessions").exists()


class TestUriPrintMode:
    def test_uri_print_renders_real_message_bodies(self, codex_session_tree, capsys):
        """URI print 模式渲染真实消息正文，含 user、assistant 与工具调用。"""
        uri = f"codex://{codex_session_tree['session_id']}"

        exit_code = run_cli(uri)
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["user_text"] in captured.out
        assert codex_session_tree["assistant_text"] in captured.out

    def test_uri_head_mode_succeeds(self, codex_session_tree, capsys):
        """--head 走 provider 的 get_session_head，输出非空且不报错。"""
        uri = f"codex://{codex_session_tree['session_id']}"

        exit_code = run_cli(uri, "--head")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert captured.out.strip()

    def test_codex_threads_uri_form_resolves_same_session(self, codex_session_tree, capsys):
        """codex://threads/<id> 与 codex://<id> 指向同一会话。"""
        uri = f"codex://threads/{codex_session_tree['session_id']}"

        exit_code = run_cli(uri)
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["user_text"] in captured.out


class TestUriExportMode:
    def test_uri_json_export_writes_parseable_file(self, codex_session_tree, tmp_path, capsys):
        """json 导出产出真实文件，内容可解析且含真实消息。"""
        uri = f"codex://{codex_session_tree['session_id']}"
        output_dir = tmp_path / "out-json"

        exit_code = run_cli(uri, "-format", "json", "-output", str(output_dir))
        capsys.readouterr()

        assert exit_code == 0
        exported = read_only_file(output_dir, ".json")
        payload = json.loads(exported.read_text(encoding="utf-8"))
        assert payload["id"] == codex_session_tree["session_id"]
        roles = [message.get("role") for message in payload["messages"]]
        assert "user" in roles and "assistant" in roles

    def test_uri_markdown_export_writes_real_markdown(self, codex_session_tree, tmp_path, capsys):
        """markdown 导出产出真实 .md，含标题与消息正文。"""
        uri = f"codex://{codex_session_tree['session_id']}"
        output_dir = tmp_path / "out-md"

        exit_code = run_cli(uri, "-format", "markdown", "-output", str(output_dir))
        capsys.readouterr()

        assert exit_code == 0
        exported = read_only_file(output_dir, ".md")
        content = exported.read_text(encoding="utf-8")
        assert codex_session_tree["user_text"] in content
        assert codex_session_tree["assistant_text"] in content

    def test_uri_raw_export_copies_source_bytes(self, codex_session_tree, tmp_path, capsys):
        """raw 导出复制原始文件，字节与源一致。"""
        uri = f"codex://{codex_session_tree['session_id']}"
        output_dir = tmp_path / "out-raw"

        exit_code = run_cli(uri, "-format", "raw", "-output", str(output_dir))
        capsys.readouterr()

        assert exit_code == 0
        exported = read_only_file(output_dir, ".jsonl")
        source_file = codex_session_tree["session_file"]
        assert exported.read_bytes() == Path(source_file).read_bytes()

    def test_multi_format_writes_file_and_prints_body(self, codex_session_tree, tmp_path, capsys):
        """json,print 同时产出文件与 stdout 正文，覆盖多格式分发接缝。"""
        uri = f"codex://{codex_session_tree['session_id']}"
        output_dir = tmp_path / "out-multi"

        exit_code = run_cli(uri, "-format", "json,print", "-output", str(output_dir))
        captured = capsys.readouterr()

        assert exit_code == 0
        assert read_only_file(output_dir, ".json").exists()
        assert codex_session_tree["user_text"] in captured.out


class TestFailurePaths:
    """失败路径必须给出诊断并以非零码退出，而不是抛 traceback。"""

    def test_unknown_session_id_exits_nonzero(self, codex_session_tree, capsys):
        exit_code = run_cli("codex://does-not-exist-0000")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert (captured.out + captured.err).strip()

    def test_unknown_uri_scheme_exits_nonzero(self, codex_session_tree, capsys):
        exit_code = run_cli("nosuchtool://abc")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert (captured.out + captured.err).strip()

    def test_unsupported_format_exits_with_usage_error(self, codex_session_tree, capsys):
        """非法 format 经 parser.error() 走 argparse 的 usage 错误码 2。"""
        uri = f"codex://{codex_session_tree['session_id']}"

        with pytest.raises(SystemExit) as excinfo:
            run_cli(uri, "-format", "totally-invalid")
        captured = capsys.readouterr()

        assert excinfo.value.code == 2
        assert "usage:" in captured.err


class TestQueryAndSearchModes:
    def test_search_finds_session_through_real_fts_index(self, codex_session_tree, capsys):
        """--search 真实建 FTS5 索引并命中，覆盖 search_index 全链路。"""
        exit_code = run_cli("--search", "登录超时", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["session_id"] in captured.out

    def test_search_miss_reports_no_result_and_exits_zero(self, codex_session_tree, capsys):
        """characterization：搜索无命中当前视为正常结果，退出码 0。"""
        exit_code = run_cli("--search", "zzznosuchtokenzzz", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["session_id"] not in captured.out

    def test_query_keyword_filters_real_sessions(self, codex_session_tree, capsys):
        """-q 关键词过滤走真实会话内容匹配。"""
        exit_code = run_cli("--list", "-q", "登录超时", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["session_id"] in captured.out


class TestMaintenanceModes:
    def test_providers_matrix_lists_every_registered_provider(self, codex_session_tree, capsys):
        """--providers 由 registry 驱动，7 个 provider 全部出现。"""
        from agent_dump.agent_registry import AGENT_REGISTRATIONS

        exit_code = run_cli("--providers")
        captured = capsys.readouterr()

        assert exit_code == 0
        for registration in AGENT_REGISTRATIONS:
            assert registration.display_name in captured.out

    def test_stats_reports_real_session_counts(self, codex_session_tree, capsys):
        exit_code = run_cli("--stats", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Codex" in captured.out


class TestDefaultOutputLocation:
    def test_export_without_output_writes_under_sessions_dir(self, codex_session_tree, capsys):
        """不指定 -output 时产物落在 CWD 下的 sessions/<agent>/，覆盖默认路径解析。"""
        uri = f"codex://{codex_session_tree['session_id']}"

        exit_code = run_cli(uri, "-format", "json")
        capsys.readouterr()

        assert exit_code == 0
        exported = read_only_file(Path.cwd() / "sessions" / "codex", ".json")
        assert exported.is_file()


# AD-145：「无可用 provider」是一种失败——命令做不到被要求的事，且这条路径走的是
# 诊断通道（错误语义）。三个模式现已一致退 1。
@pytest.mark.parametrize("flag", ["--list", "--stats", "--reindex"])
def test_modes_report_diagnostic_when_no_provider_has_data(isolated_provider_home, flag, capsys):
    """空 home 下各模式输出诊断并以 1 退出，脚本能检测到。"""
    exit_code = run_cli(flag, "-d", "36500")
    captured = capsys.readouterr()

    assert exit_code == 1, f"{flag} 在无 provider 数据时应退 1"
    assert "诊断信息" in captured.out


def test_reindex_succeeds_on_a_cache_that_never_had_an_index(codex_session_tree, capsys):
    """回归：rebuild() 先 clear 再 update，首次运行时 FTS 表尚不存在。

    修复前 clear_agent() 未建表就 DELETE，抛
    sqlite3.OperationalError: no such table: sessions_fts。
    """
    exit_code = run_cli("--reindex", "-d", "36500")
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Codex" in captured.out


class TestProviderFailureIsolation:
    """AD-122：一个 provider 的坏数据不得让整条命令带 traceback 退出。"""

    def test_list_still_reports_healthy_provider_when_another_raises(self, codex_session_tree, monkeypatch, capsys):
        from agent_dump.agents.claudecode import ClaudeCodeAgent

        monkeypatch.setattr(ClaudeCodeAgent, "is_available", lambda self: True)
        monkeypatch.setattr(
            ClaudeCodeAgent,
            "get_sessions",
            lambda self, days=7: (_ for _ in ()).throw(ValueError("malformed row")),
        )

        exit_code = run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert codex_session_tree["title"] in captured.out, "健康 provider 的结果必须照常出现"
        assert "Claude Code" in captured.err and "ValueError" in captured.err


class TestTopLevelErrorHandling:
    """AD-122：漏到最外层的异常必须渲染成诊断，而不是 traceback。"""

    def test_unexpected_exception_becomes_a_diagnostic(self, codex_session_tree, monkeypatch, capsys):
        monkeypatch.setattr(
            "agent_dump.cli._run",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        exit_code = run_cli("--list")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "诊断信息" in captured.out
        assert "RuntimeError: boom" in captured.out

    def test_diagnostic_error_is_rendered_without_the_generic_wrapper(self, codex_session_tree, monkeypatch, capsys):
        from agent_dump.diagnostics import root_not_found

        def _raise():
            raise root_not_found("自定义诊断。", searched_roots=("root-a",))

        monkeypatch.setattr("agent_dump.cli._run", _raise)

        exit_code = run_cli("--list")
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "自定义诊断。" in captured.out
        assert "未预期的错误" not in captured.out

    def test_system_exit_still_propagates(self, codex_session_tree):
        """argparse 的 --help / -v / usage error 依赖 SystemExit 原样抛出。"""
        with pytest.raises(SystemExit) as excinfo:
            run_cli("--version")

        assert excinfo.value.code == 0


class TestSessionDataIsParsedOncePerCommand:
    """AD-125：单条命令内同一会话只应完整解析一次。"""

    @staticmethod
    def _count_parses(monkeypatch) -> list[str]:
        from agent_dump.agents.codex import CodexAgent

        parses: list[str] = []
        original = CodexAgent.get_session_data

        def counting(self, session):
            parses.append(session.id)
            return original(self, session)

        monkeypatch.setattr(CodexAgent, "get_session_data", counting)
        return parses

    def test_uri_json_and_print_parses_once(self, codex_session_tree, tmp_path, monkeypatch, capsys):
        parses = self._count_parses(monkeypatch)
        uri = f"codex://{codex_session_tree['session_id']}"

        exit_code = run_cli(uri, "-format", "json,print", "-output", str(tmp_path / "o1"))
        capsys.readouterr()

        assert exit_code == 0
        assert len(parses) == 1, f"json+print 应只解析一次，实际 {len(parses)} 次"

    def test_uri_json_and_markdown_parses_once(self, codex_session_tree, tmp_path, monkeypatch, capsys):
        parses = self._count_parses(monkeypatch)
        uri = f"codex://{codex_session_tree['session_id']}"

        exit_code = run_cli(uri, "-format", "json,markdown", "-output", str(tmp_path / "o2"))
        capsys.readouterr()

        assert exit_code == 0
        assert len(parses) == 1, f"json+markdown 应只解析一次，实际 {len(parses)} 次"

    def test_query_match_then_export_parses_once(self, codex_session_tree, tmp_path, monkeypatch, capsys):
        """关键词匹配已解析过，导出不应再解析一遍。"""
        parses = self._count_parses(monkeypatch)

        exit_code = run_cli(
            "--list", "-q", "登录超时", "-d", "36500", "-format", "json", "-output", str(tmp_path / "o3")
        )
        capsys.readouterr()

        assert exit_code == 0
        assert len(parses) == 1, f"查询+导出应只解析一次，实际 {len(parses)} 次"

    def test_codex_json_export_does_not_corrupt_the_cached_data(
        self, codex_session_tree, tmp_path, monkeypatch, capsys
    ):
        """Codex 的 JSON 导出变换必须作用在副本上，不能污染 markdown 看到的数据。"""
        uri = f"codex://{codex_session_tree['session_id']}"
        out = tmp_path / "o4"

        exit_code = run_cli(uri, "-format", "json,markdown", "-output", str(out))
        capsys.readouterr()

        assert exit_code == 0
        markdown = read_only_file(out, ".md").read_text(encoding="utf-8")
        assert codex_session_tree["user_text"] in markdown
        assert codex_session_tree["assistant_text"] in markdown


class TestInteractiveModeScansOnce:
    """AD-128：交互模式不得把同一个 provider 扫两遍。"""

    def test_interactive_without_query_scans_each_provider_once(self, two_provider_tree, monkeypatch, capsys):
        """两个 provider 可选时才会走 selector；单 provider 会自动选中并绕开它。

        这里刻意不 mock selector——修复前的重复扫描恰恰发生在 selector 内部渲染
        「(N 个会话)」标签的时候。非 TTY 环境走 select_agent_simple，只需 mock input。
        修复前：['claudecode', 'codex', 'codex']（选中的 provider 被扫第二遍）。
        """
        # codex 与 claudecode 都继承 FileSessionAgent 的 get_sessions，
        # 打在 BaseAgent 上会被子类实现绕过
        from agent_dump.agents.file_sessions import FileSessionAgent

        scans: list[str] = []
        original = FileSessionAgent.get_sessions

        def counting(self, days=7):
            scans.append(self.name)
            return original(self, days)

        monkeypatch.setattr(FileSessionAgent, "get_sessions", counting)
        monkeypatch.setattr(
            "agent_dump.session_workflow.select_sessions_interactive",
            lambda sessions, agent, show_metadata_summary=True: [],
        )

        with mock.patch("builtins.input", return_value="1"):
            run_cli("--interactive", "-d", "36500")
        capsys.readouterr()

        assert sorted(scans) == ["claudecode", "codex"], f"每个 provider 应恰好扫一次，实际 {sorted(scans)}"


class TestUntrustedTextCannotReachOutput:
    """AD-132：会话内容由别的工具写入，控制字符不得抵达终端或导出文件。"""

    def test_list_output_carries_no_control_characters(self, hostile_codex_session, capsys):
        from agent_dump.text_safety import has_unsafe_body_characters

        exit_code = run_cli("--list", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert not has_unsafe_body_characters(captured.out), "列表输出仍含控制字符"
        assert "HIJACKED" in captured.out, "净化应只剥离控制字符，不丢弃可见文本"

    def test_uri_print_output_carries_no_control_characters(self, hostile_codex_session, capsys):
        from agent_dump.text_safety import has_unsafe_body_characters

        exit_code = run_cli(f"codex://{hostile_codex_session['session_id']}")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert not has_unsafe_body_characters(captured.out)

    def test_head_output_carries_no_control_characters(self, hostile_codex_session, capsys):
        from agent_dump.text_safety import has_unsafe_body_characters

        exit_code = run_cli(f"codex://{hostile_codex_session['session_id']}", "--head")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert not has_unsafe_body_characters(captured.out)

    def test_markdown_export_carries_no_control_characters(self, hostile_codex_session, tmp_path, capsys):
        from agent_dump.text_safety import has_unsafe_body_characters

        out = tmp_path / "md"
        exit_code = run_cli(
            f"codex://{hostile_codex_session['session_id']}", "-format", "markdown", "-output", str(out)
        )
        capsys.readouterr()

        assert exit_code == 0
        content = read_only_file(out, ".md").read_text(encoding="utf-8")
        assert not has_unsafe_body_characters(content), "导出的 markdown 仍含控制字符"
        assert "答复正文" in content, "正文的可见内容必须完整保留"
        assert "\n" in content, "正文换行是内容的一部分，不能被压掉"

    def test_search_output_carries_no_control_characters(self, hostile_codex_session, capsys):
        from agent_dump.text_safety import has_unsafe_body_characters

        exit_code = run_cli("--search", "答复正文", "-d", "36500")
        captured = capsys.readouterr()

        assert exit_code == 0
        assert not has_unsafe_body_characters(captured.out)


class TestControlCharactersInSessionIdAreRejected:
    """AD-132：文件名此前只拦 NUL，CR/LF/ESC 能存活并被回显。"""

    @pytest.mark.parametrize("bad_id", ["ok\rmalicious", "ok\nmalicious", "ok\x1b[2Kmalicious", "ok\x00malicious"])
    def test_control_characters_are_refused(self, bad_id):
        from agent_dump.diagnostics import DiagnosticError
        from agent_dump.export_paths import safe_session_filename

        with pytest.raises(DiagnosticError):
            safe_session_filename(bad_id)

    @pytest.mark.parametrize("good_id", ["019c213e-c251-73a3", "session_1", "会话-1"])
    def test_ordinary_ids_still_work(self, good_id):
        from agent_dump.export_paths import safe_session_filename

        assert safe_session_filename(good_id) == good_id


class TestExitCodeConvention:
    """AD-145：退出码约定，钉成可执行的矩阵而不是散落在各测试里的断言。

    0 = 命令做到了被要求的事（哪怕结果集为空）
    1 = 命令做不到（本机无 provider 数据、URI 未解析、参数组合非法）
    2 = argparse 的用法错误
    """

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(("--list", "-d", "1"), id="window-excludes-everything"),
            pytest.param(("--list", "-q", "zzznosuchtokenzzz", "-d", "36500"), id="keyword-miss"),
            pytest.param(("--search", "zzznosuchtokenzzz", "-d", "36500"), id="search-miss"),
            pytest.param(("--stats", "-d", "1"), id="stats-window-empty"),
            pytest.param(("--providers",), id="capability-matrix"),
        ],
    )
    def test_zero_when_the_command_succeeded_with_an_empty_result(self, codex_session_tree, argv, capsys):
        """「没有匹配的东西」不是失败——provider 可用，命令也确实执行了。"""
        exit_code = run_cli(*argv)
        capsys.readouterr()

        assert exit_code == 0

    @pytest.mark.parametrize(
        "argv",
        [
            pytest.param(("codex://no-such-session-id",), id="unresolvable-uri"),
            pytest.param(("nosuchtool://abc",), id="unknown-scheme"),
        ],
    )
    def test_one_when_the_command_could_not_do_what_was_asked(self, codex_session_tree, argv, capsys):
        exit_code = run_cli(*argv)
        capsys.readouterr()

        assert exit_code == 1

    @pytest.mark.parametrize("flag", ["--list", "--stats", "--reindex"])
    def test_one_when_no_provider_data_exists_at_all(self, isolated_provider_home, flag, capsys):
        """这是 AD-145 修的那处：--list 曾在此退 0，而同条件下另两个退 1。"""
        exit_code = run_cli(flag, "-d", "36500")
        capsys.readouterr()

        assert exit_code == 1

    def test_two_for_argparse_usage_errors(self, codex_session_tree, capsys):
        with pytest.raises(SystemExit) as excinfo:
            run_cli(f"codex://{codex_session_tree['session_id']}", "-format", "totally-invalid")
        capsys.readouterr()

        assert excinfo.value.code == 2
