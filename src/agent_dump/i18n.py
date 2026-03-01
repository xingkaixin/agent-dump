"""
Internationalization support for agent-dump
"""

import locale
import os


# Translation keys
class Keys:
    URI_INVALID_FORMAT = "URI_INVALID_FORMAT"
    URI_SUPPORTED_FORMATS = "URI_SUPPORTED_FORMATS"
    NO_AGENTS_FOUND = "NO_AGENTS_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    URI_SCHEME_MISMATCH = "URI_SCHEME_MISMATCH"
    URI_BELONGS_TO = "URI_BELONGS_TO"
    FETCH_DATA_FAILED = "FETCH_DATA_FAILED"
    QUERY_INVALID = "QUERY_INVALID"
    SUPPORTED_AGENTS = "SUPPORTED_AGENTS"
    NO_AGENTS_IN_QUERY = "NO_AGENTS_IN_QUERY"
    LIST_HEADER_FILTERED = "LIST_HEADER_FILTERED"
    LIST_HEADER = "LIST_HEADER"
    NO_SESSIONS_IN_DAYS = "NO_SESSIONS_IN_DAYS"
    HINT_INTERACTIVE = "HINT_INTERACTIVE"
    NO_SESSIONS_MATCHING_KEYWORD = "NO_SESSIONS_MATCHING_KEYWORD"
    AUTO_SELECT_AGENT = "AUTO_SELECT_AGENT"
    NO_AGENT_SELECTED = "NO_AGENT_SELECTED"
    AGENT_SELECTED = "AGENT_SELECTED"
    NO_SESSIONS_FOUND = "NO_SESSIONS_FOUND"
    SESSIONS_FOUND_FILTERED = "SESSIONS_FOUND_FILTERED"
    SESSIONS_FOUND = "SESSIONS_FOUND"
    MANY_SESSIONS_WARNING = "MANY_SESSIONS_WARNING"
    MANY_SESSIONS_EXAMPLE = "MANY_SESSIONS_EXAMPLE"
    NO_SESSION_SELECTED = "NO_SESSION_SELECTED"
    SESSIONS_SELECTED_COUNT = "SESSIONS_SELECTED_COUNT"
    EXPORTING_AGENT = "EXPORTING_AGENT"
    EXPORT_SUCCESS = "EXPORT_SUCCESS"
    EXPORT_ERROR = "EXPORT_ERROR"
    EXPORT_SUCCESS_FORMAT = "EXPORT_SUCCESS_FORMAT"
    EXPORT_ERROR_FORMAT = "EXPORT_ERROR_FORMAT"
    EXPORT_SUMMARY = "EXPORT_SUMMARY"
    NO_SESSIONS_PAREN = "NO_SESSIONS_PAREN"
    PAGINATION_INFO = "PAGINATION_INFO"
    PAGINATION_PROMPT = "PAGINATION_PROMPT"
    PAGINATION_DONE = "PAGINATION_DONE"
    PAGINATION_REMAINING = "PAGINATION_REMAINING"
    SCANNING_AGENTS = "SCANNING_AGENTS"
    AGENT_FOUND = "AGENT_FOUND"
    AGENT_FOUND_EMPTY = "AGENT_FOUND_EMPTY"

    # Time
    TIME_TODAY = "TIME_TODAY"
    TIME_YESTERDAY = "TIME_YESTERDAY"
    TIME_THIS_WEEK = "TIME_THIS_WEEK"
    TIME_THIS_MONTH = "TIME_THIS_MONTH"
    TIME_OLDER = "TIME_OLDER"
    TIME_UNKNOWN = "TIME_UNKNOWN"
    TIME_MINUTES_AGO = "TIME_MINUTES_AGO"
    TIME_JUST_NOW = "TIME_JUST_NOW"
    TIME_HOURS_AGO = "TIME_HOURS_AGO"
    TIME_DAYS_AGO = "TIME_DAYS_AGO"
    TIME_WEEKS_AGO = "TIME_WEEKS_AGO"

    # Selector
    SELECT_AGENT_PROMPT = "SELECT_AGENT_PROMPT"
    SELECT_INSTRUCTION = "SELECT_INSTRUCTION"
    USER_CANCELLED = "USER_CANCELLED"
    AVAILABLE_AGENTS = "AVAILABLE_AGENTS"
    SELECT_AGENT_NUMBER = "SELECT_AGENT_NUMBER"
    NO_INPUT_EXITING = "NO_INPUT_EXITING"
    INVALID_SELECTION = "INVALID_SELECTION"
    INVALID_INPUT_NUMBER = "INVALID_INPUT_NUMBER"
    NO_SESSIONS_IN_RANGE = "NO_SESSIONS_IN_RANGE"
    GROUP_TITLE = "GROUP_TITLE"
    SELECT_SESSIONS_PROMPT = "SELECT_SESSIONS_PROMPT"
    CHECKBOX_INSTRUCTION = "CHECKBOX_INSTRUCTION"
    AVAILABLE_SESSIONS = "AVAILABLE_SESSIONS"
    ENTER_SESSION_NUMBERS = "ENTER_SESSION_NUMBERS"
    INVALID_INPUT_NUMBERS = "INVALID_INPUT_NUMBERS"

    # CLI Help
    CLI_DESC = "CLI_DESC"
    CLI_URI_HELP = "CLI_URI_HELP"
    CLI_DAYS_HELP = "CLI_DAYS_HELP"
    CLI_OUTPUT_HELP = "CLI_OUTPUT_HELP"
    CLI_FORMAT_HELP = "CLI_FORMAT_HELP"
    CLI_LIST_HELP = "CLI_LIST_HELP"
    CLI_INTERACTIVE_HELP = "CLI_INTERACTIVE_HELP"
    CLI_PAGE_SIZE_HELP = "CLI_PAGE_SIZE_HELP"
    CLI_QUERY_HELP = "CLI_QUERY_HELP"
    CLI_LANG_HELP = "CLI_LANG_HELP"
    CLI_FORMAT_INVALID = "CLI_FORMAT_INVALID"
    LIST_IGNORE_FORMAT = "LIST_IGNORE_FORMAT"
    LIST_IGNORE_OUTPUT = "LIST_IGNORE_OUTPUT"
    INTERACTIVE_FORMAT_INVALID = "INTERACTIVE_FORMAT_INVALID"
    URI_EXPORT_SAVED = "URI_EXPORT_SAVED"

    # Misc
    SESSION_COUNT_SUFFIX = "SESSION_COUNT_SUFFIX"


TRANSLATIONS = {
    "en": {
        Keys.URI_INVALID_FORMAT: "❌ Invalid URI format: {uri}",
        Keys.URI_SUPPORTED_FORMATS: "\nSupported URI formats:",
        Keys.NO_AGENTS_FOUND: "❌ No available Agent Tools sessions found.",
        Keys.SESSION_NOT_FOUND: "❌ Session not found: {uri}",
        Keys.URI_SCHEME_MISMATCH: "❌ URI scheme mismatch: {uri}",
        Keys.URI_BELONGS_TO: "   Session belongs to {agent_display_name}, but URI used {scheme}://",
        Keys.FETCH_DATA_FAILED: "❌ Failed to fetch session data: {error}",
        Keys.QUERY_INVALID: "❌ Invalid -query parameter: {error}",
        Keys.SUPPORTED_AGENTS: "\nSupported Agent Tools:",
        Keys.NO_AGENTS_IN_QUERY: "⚠️  No available Agent Tools in query scope.",
        Keys.LIST_HEADER_FILTERED: "📋 Listing sessions from last {days} days matching '{keyword}':\n",
        Keys.LIST_HEADER: "📋 Listing sessions from last {days} days:\n",
        Keys.NO_SESSIONS_IN_DAYS: "   (No sessions in last {days} days)",
        Keys.HINT_INTERACTIVE: "Hint: Use --interactive for interactive export mode",
        Keys.NO_SESSIONS_MATCHING_KEYWORD: "⚠️  No sessions found in last {days} days matching '{keyword}'.",
        Keys.AUTO_SELECT_AGENT: "Auto-selected: {agent_name}\n",
        Keys.NO_AGENT_SELECTED: "⚠️  No Agent Tool selected, exiting.",
        Keys.AGENT_SELECTED: "\nSelected: {agent_name}\n",
        Keys.NO_SESSIONS_FOUND: "⚠️  No sessions found in last {days} days.",
        Keys.SESSIONS_FOUND_FILTERED: "📊 Found {count} sessions (last {days} days, matching '{keyword}')\n",
        Keys.SESSIONS_FOUND: "📊 Found {count} sessions (last {days} days)\n",
        Keys.MANY_SESSIONS_WARNING: "⚠️  Note: Many sessions ({count}), consider using -days to narrow range",
        Keys.MANY_SESSIONS_EXAMPLE: "   Example: agent-dump --interactive -days 1\n",
        Keys.NO_SESSION_SELECTED: "⚠️  No session selected, exiting.",
        Keys.SESSIONS_SELECTED_COUNT: "\n✓ Selected {count} sessions\n",
        Keys.EXPORTING_AGENT: "📤 Exporting {agent_name} sessions...",
        Keys.EXPORT_SUCCESS: "  ✓ {title}... → {filename}",
        Keys.EXPORT_ERROR: "  ✗ {title}... → Error: {error}",
        Keys.EXPORT_SUCCESS_FORMAT: "  ✓ {title}... [{format}] → {filename}",
        Keys.EXPORT_ERROR_FORMAT: "  ✗ {title}... [{format}] → Error: {error}",
        Keys.EXPORT_SUMMARY: "\n✅ Successfully exported {count} sessions to {path}/",
        Keys.NO_SESSIONS_PAREN: "   (No sessions)",
        Keys.PAGINATION_INFO: "   Page {current}/{total} (Total {total_sessions} sessions)",
        Keys.PAGINATION_PROMPT: "   Press Enter for more, or 'q' to quit",
        Keys.PAGINATION_DONE: "   All sessions displayed",
        Keys.PAGINATION_REMAINING: "   ... {count} more sessions not shown",
        Keys.SCANNING_AGENTS: "🔍 Scanning Agent Tools...\n",
        Keys.AGENT_FOUND: "   ✓ Found {name} ({count} sessions)",
        Keys.AGENT_FOUND_EMPTY: "   ⚠ Found {name} (0 sessions)",
        Keys.TIME_TODAY: "Today",
        Keys.TIME_YESTERDAY: "Yesterday",
        Keys.TIME_THIS_WEEK: "This Week",
        Keys.TIME_THIS_MONTH: "This Month",
        Keys.TIME_OLDER: "Older",
        Keys.TIME_UNKNOWN: "Unknown Time",
        Keys.TIME_MINUTES_AGO: "{minutes} mins ago",
        Keys.TIME_JUST_NOW: "Just now",
        Keys.TIME_HOURS_AGO: "{hours} hours ago",
        Keys.TIME_DAYS_AGO: "{days} days ago",
        Keys.TIME_WEEKS_AGO: "{weeks} weeks ago",
        Keys.SELECT_AGENT_PROMPT: "Select Agent Tool to export:",
        Keys.SELECT_INSTRUCTION: "\n↑↓ Move  |  Enter Select  |  q Quit",
        Keys.USER_CANCELLED: "⚠️  User cancelled, exiting.",
        Keys.AVAILABLE_AGENTS: "Available Agent Tools:",
        Keys.SELECT_AGENT_NUMBER: "Select Agent Tool number:",
        Keys.NO_INPUT_EXITING: "⚠️  No input provided. Exiting.",
        Keys.INVALID_SELECTION: "⚠️  Invalid selection: {selection}",
        Keys.INVALID_INPUT_NUMBER: "⚠️  Invalid input. Please enter a number.",
        Keys.NO_SESSIONS_IN_RANGE: "No sessions found in the specified time range.",
        Keys.GROUP_TITLE: "─── {group_name} ({count}) ───",
        Keys.SELECT_SESSIONS_PROMPT: "Select sessions to export:",
        Keys.CHECKBOX_INSTRUCTION: "\n↑↓ Move  |  Space Select/Toggle  |  Enter Confirm  |  q Quit",
        Keys.AVAILABLE_SESSIONS: "Available sessions:",
        Keys.ENTER_SESSION_NUMBERS: "Enter session numbers to export (comma-separated, e.g., '1,3,5' or 'all'):",
        Keys.INVALID_INPUT_NUMBERS: "⚠️  Invalid input. Please enter numbers separated by commas.",
        Keys.CLI_DESC: "Export agent sessions",
        Keys.CLI_URI_HELP: "Agent session URI to dump (e.g., opencode://session-id)",
        Keys.CLI_DAYS_HELP: "Number of days to look back (default: 7)",
        Keys.CLI_OUTPUT_HELP: "Output base directory (default: ./sessions)",
        Keys.CLI_FORMAT_HELP: "Output format: json | markdown | raw | print (comma-separated, md alias supported)",
        Keys.CLI_LIST_HELP: "List all available sessions without exporting",
        Keys.CLI_INTERACTIVE_HELP: "Run in interactive mode to select and export sessions",
        Keys.CLI_PAGE_SIZE_HELP: "Number of sessions to display per page (default: 20)",
        Keys.CLI_QUERY_HELP: "Query filter, supports 'agent1,agent2:keyword' or 'keyword'",
        Keys.CLI_LANG_HELP: "Language (en, zh). Default: auto-detect",
        Keys.CLI_FORMAT_INVALID: "invalid format list: {value}",
        Keys.LIST_IGNORE_FORMAT: "⚠️  --list mode ignores -format/--format.",
        Keys.LIST_IGNORE_OUTPUT: "⚠️  --list mode ignores -output/--output.",
        Keys.INTERACTIVE_FORMAT_INVALID: "❌ --interactive mode does not support print; use json, markdown, or raw.",
        Keys.URI_EXPORT_SAVED: "✅ Exported session [{format}] to: {path}",
        Keys.SESSION_COUNT_SUFFIX: "sessions",
    },
    "zh": {
        Keys.URI_INVALID_FORMAT: "❌ 无效的 URI 格式: {uri}",
        Keys.URI_SUPPORTED_FORMATS: "\n支持的 URI 格式:",
        Keys.NO_AGENTS_FOUND: "❌ 未找到任何可用的 Agent Tools 会话。",
        Keys.SESSION_NOT_FOUND: "❌ 未找到会话: {uri}",
        Keys.URI_SCHEME_MISMATCH: "❌ URI scheme 与会话不匹配: {uri}",
        Keys.URI_BELONGS_TO: "   该会话属于 {agent_display_name}，但 URI 使用了 {scheme}://",
        Keys.FETCH_DATA_FAILED: "❌ 获取会话数据失败: {error}",
        Keys.QUERY_INVALID: "❌ 无效的 -query 参数: {error}",
        Keys.SUPPORTED_AGENTS: "\n支持的 Agent Tools:",
        Keys.NO_AGENTS_IN_QUERY: "⚠️  查询范围内没有可用的 Agent Tools。",
        Keys.LIST_HEADER_FILTERED: "📋 列出最近 {days} 天且匹配「{keyword}」的会话:\n",
        Keys.LIST_HEADER: "📋 列出最近 {days} 天的会话:\n",
        Keys.NO_SESSIONS_IN_DAYS: "   (最近 {days} 天内无会话)",
        Keys.HINT_INTERACTIVE: "提示: 使用 --interactive 进入交互式导出模式",
        Keys.NO_SESSIONS_MATCHING_KEYWORD: "⚠️  未找到最近 {days} 天内匹配「{keyword}」的会话。",
        Keys.AUTO_SELECT_AGENT: "自动选择: {agent_name}\n",
        Keys.NO_AGENT_SELECTED: "⚠️  未选择 Agent Tool，退出。",
        Keys.AGENT_SELECTED: "\n已选择: {agent_name}\n",
        Keys.NO_SESSIONS_FOUND: "⚠️  未找到最近 {days} 天内的会话。",
        Keys.SESSIONS_FOUND_FILTERED: "📊 找到 {count} 个会话 (最近 {days} 天，匹配「{keyword}」)\n",
        Keys.SESSIONS_FOUND: "📊 找到 {count} 个会话 (最近 {days} 天)\n",
        Keys.MANY_SESSIONS_WARNING: "⚠️  注意: 会话数量较多 ({count} 个)，建议使用 -days 缩小时间范围",
        Keys.MANY_SESSIONS_EXAMPLE: "   例如: agent-dump --interactive -days 1\n",
        Keys.NO_SESSION_SELECTED: "⚠️  未选择会话，退出。",
        Keys.SESSIONS_SELECTED_COUNT: "\n✓ 选择了 {count} 个会话\n",
        Keys.EXPORTING_AGENT: "📤 导出 {agent_name} 会话...",
        Keys.EXPORT_SUCCESS: "  ✓ {title}... → {filename}",
        Keys.EXPORT_ERROR: "  ✗ {title}... → 错误: {error}",
        Keys.EXPORT_SUCCESS_FORMAT: "  ✓ {title}... [{format}] → {filename}",
        Keys.EXPORT_ERROR_FORMAT: "  ✗ {title}... [{format}] → 错误: {error}",
        Keys.EXPORT_SUMMARY: "\n✅ 成功导出 {count} 个会话到 {path}/",
        Keys.NO_SESSIONS_PAREN: "   (无会话)",
        Keys.PAGINATION_INFO: "   第 {current}/{total} 页 (共 {total_sessions} 个会话)",
        Keys.PAGINATION_PROMPT: "   按 Enter 查看更多，或输入 'q' 退出",
        Keys.PAGINATION_DONE: "   已显示全部会话",
        Keys.PAGINATION_REMAINING: "   ... 还有 {count} 个会话未显示",
        Keys.SCANNING_AGENTS: "🔍 正在扫描 Agent Tools...\n",
        Keys.AGENT_FOUND: "   ✓ 发现 {name} ({count} 个会话)",
        Keys.AGENT_FOUND_EMPTY: "   ⚠ 发现 {name} (0 个会话)",
        Keys.TIME_TODAY: "今天",
        Keys.TIME_YESTERDAY: "昨天",
        Keys.TIME_THIS_WEEK: "本周",
        Keys.TIME_THIS_MONTH: "本月",
        Keys.TIME_OLDER: "更早",
        Keys.TIME_UNKNOWN: "未知时间",
        Keys.TIME_MINUTES_AGO: "{minutes} 分钟前",
        Keys.TIME_JUST_NOW: "刚刚",
        Keys.TIME_HOURS_AGO: "{hours} 小时前",
        Keys.TIME_DAYS_AGO: "{days} 天前",
        Keys.TIME_WEEKS_AGO: "{weeks} 周前",
        Keys.SELECT_AGENT_PROMPT: "选择要导出的 Agent Tool:",
        Keys.SELECT_INSTRUCTION: "\n↑↓ 移动  |  回车 选择  |  q 退出",
        Keys.USER_CANCELLED: "⚠️  用户取消操作，退出。",
        Keys.AVAILABLE_AGENTS: "可用的 Agent Tools:",
        Keys.SELECT_AGENT_NUMBER: "选择 Agent Tool 编号:",
        Keys.NO_INPUT_EXITING: "⚠️  No input provided. Exiting.",
        Keys.INVALID_SELECTION: "⚠️  Invalid selection: {selection}",
        Keys.INVALID_INPUT_NUMBER: "⚠️  Invalid input. Please enter a number.",
        Keys.NO_SESSIONS_IN_RANGE: "No sessions found in the specified time range.",
        Keys.GROUP_TITLE: "─── {group_name} ({count} 个) ───",
        Keys.SELECT_SESSIONS_PROMPT: "选择要导出的会话:",
        Keys.CHECKBOX_INSTRUCTION: "\n↑↓ 移动  |  空格 选择/取消  |  回车 确认  |  q 退出",
        Keys.AVAILABLE_SESSIONS: "Available sessions:",
        Keys.ENTER_SESSION_NUMBERS: "Enter session numbers to export (comma-separated, e.g., '1,3,5' or 'all'):",
        Keys.INVALID_INPUT_NUMBERS: "⚠️  Invalid input. Please enter numbers separated by commas.",
        Keys.CLI_DESC: "导出 Agent 会话",
        Keys.CLI_URI_HELP: "要导出的 Agent 会话 URI (例如: opencode://session-id)",
        Keys.CLI_DAYS_HELP: "查找最近几天的会话 (默认: 7)",
        Keys.CLI_OUTPUT_HELP: "输出目录 (默认: ./sessions)",
        Keys.CLI_FORMAT_HELP: "输出格式: json | markdown | raw | print（支持逗号分隔，兼容 md 别名）",
        Keys.CLI_LIST_HELP: "列出所有可用会话而不导出",
        Keys.CLI_INTERACTIVE_HELP: "进入交互式模式选择并导出",
        Keys.CLI_PAGE_SIZE_HELP: "每页显示的会话数量 (默认: 20)",
        Keys.CLI_QUERY_HELP: "查询过滤器，支持 'agent1,agent2:关键词' 或 '关键词'",
        Keys.CLI_LANG_HELP: "语言 (en, zh). 默认: 自动检测",
        Keys.CLI_FORMAT_INVALID: "无效的格式列表: {value}",
        Keys.LIST_IGNORE_FORMAT: "⚠️  --list 模式会忽略 -format/--format 参数。",
        Keys.LIST_IGNORE_OUTPUT: "⚠️  --list 模式会忽略 -output/--output 参数。",
        Keys.INTERACTIVE_FORMAT_INVALID: "❌ --interactive 模式不支持 print；可用格式为 json、markdown、raw。",
        Keys.URI_EXPORT_SAVED: "✅ 已导出 [{format}] 到: {path}",
        Keys.SESSION_COUNT_SUFFIX: "个会话",
    },
}


class I18n:
    def __init__(self):
        self.lang = "en"
        self.translations = TRANSLATIONS

    def set_language(self, lang):
        if lang in self.translations:
            self.lang = lang
        else:
            # Fallback to English if not supported
            self.lang = "en"

    def detect_language(self):
        # Check environment variables first
        lang = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
        if "zh" in lang.lower():
            return "zh"

        # Check locale
        try:
            loc = locale.getdefaultlocale()
            if loc and loc[0] and "zh" in loc[0].lower():
                return "zh"
        except Exception:  # noqa: S110
            pass

        return "en"

    def t(self, key: str, **kwargs) -> str:
        lang_dict = self.translations.get(self.lang, {})
        msg = lang_dict.get(key)

        if msg is None:
            # Fallback to English
            msg = self.translations.get("en", {}).get(key, key)

        # Should strictly be a string if keys are managed correctly,
        # but for type safety we ensure it is not None.
        if msg is None:
            msg = key

        if kwargs:
            try:
                return msg.format(**kwargs)
            except KeyError:
                return msg
        return msg


# Global instance
i18n = I18n()


def setup_i18n(lang_arg=None):
    """
    Initialize i18n with detection logic.
    Priority:
    1. Command line argument (--lang)
    2. Environment variables / Locale
    3. Default (en)
    """
    if lang_arg:
        i18n.set_language(lang_arg)
        return

    detected = i18n.detect_language()
    i18n.set_language(detected)
