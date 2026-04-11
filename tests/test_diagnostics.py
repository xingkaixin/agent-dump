"""测试诊断错误渲染。"""

from agent_dump.diagnostics import DiagnosticError, ParsedUri, render_diagnostic
from agent_dump.i18n import i18n


class TestDiagnostics:
    def test_render_diagnostic_omits_empty_sections(self):
        i18n.set_language("zh")
        rendered = render_diagnostic(DiagnosticError(summary="示例错误"), t=i18n.t)

        assert "结论: 示例错误" in rendered
        assert "证据" not in rendered
        assert "searched roots" not in rendered

    def test_render_diagnostic_includes_all_sections(self):
        i18n.set_language("zh")
        rendered = render_diagnostic(
            DiagnosticError(
                summary="未找到会话",
                details=("detail-a",),
                searched_roots=("Codex: CODEX_HOME/sessions: /tmp/codex",),
                parsed_uri=ParsedUri(raw="codex://session-1", scheme="codex", session_id="session-1"),
                capability_gap="raw export is unsupported",
                next_steps=("先运行 `agent-dump --list`。",),
            ),
            t=i18n.t,
        )

        assert "解析后的 URI: codex://session-1" in rendered
        assert "证据:" in rendered
        assert "searched roots:" in rendered
        assert "缺失能力: raw export is unsupported" in rendered
        assert "下一步:" in rendered
