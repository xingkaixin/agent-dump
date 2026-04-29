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
    CLI_HEAD_HELP = "CLI_HEAD_HELP"
    CLI_SUMMARY_HELP = "CLI_SUMMARY_HELP"
    CLI_LIST_HELP = "CLI_LIST_HELP"
    CLI_INTERACTIVE_HELP = "CLI_INTERACTIVE_HELP"
    CLI_NO_METADATA_SUMMARY_HELP = "CLI_NO_METADATA_SUMMARY_HELP"
    CLI_SAVE_HELP = "CLI_SAVE_HELP"
    CLI_PAGE_SIZE_HELP = "CLI_PAGE_SIZE_HELP"
    CLI_QUERY_HELP = "CLI_QUERY_HELP"
    CLI_LANG_HELP = "CLI_LANG_HELP"
    CLI_COLLECT_HELP = "CLI_COLLECT_HELP"
    CLI_COLLECT_MODE_HELP = "CLI_COLLECT_MODE_HELP"
    CLI_SHORTCUT_HELP = "CLI_SHORTCUT_HELP"
    CLI_SINCE_HELP = "CLI_SINCE_HELP"
    CLI_UNTIL_HELP = "CLI_UNTIL_HELP"
    CLI_CONFIG_HELP = "CLI_CONFIG_HELP"
    CLI_STATS_HELP = "CLI_STATS_HELP"
    CLI_SEARCH_HELP = "CLI_SEARCH_HELP"
    CLI_REINDEX_HELP = "CLI_REINDEX_HELP"
    CLI_VERSION_HELP = "CLI_VERSION_HELP"
    CLI_FORMAT_INVALID = "CLI_FORMAT_INVALID"
    SEARCH_INDEX_NOT_AVAILABLE = "SEARCH_INDEX_NOT_AVAILABLE"
    REINDEX_START = "REINDEX_START"
    REINDEX_AGENT_DONE = "REINDEX_AGENT_DONE"
    REINDEX_DONE = "REINDEX_DONE"
    LIST_IGNORE_FORMAT = "LIST_IGNORE_FORMAT"
    LIST_IGNORE_OUTPUT = "LIST_IGNORE_OUTPUT"
    INTERACTIVE_FORMAT_INVALID = "INTERACTIVE_FORMAT_INVALID"
    URI_EXPORT_SAVED = "URI_EXPORT_SAVED"
    URI_SUMMARY_NO_JSON_WARNING = "URI_SUMMARY_NO_JSON_WARNING"
    URI_SUMMARY_CONFIG_MISSING_WARNING = "URI_SUMMARY_CONFIG_MISSING_WARNING"
    URI_SUMMARY_CONFIG_INCOMPLETE_WARNING = "URI_SUMMARY_CONFIG_INCOMPLETE_WARNING"
    URI_SUMMARY_API_FAILED_WARNING = "URI_SUMMARY_API_FAILED_WARNING"
    URI_SUMMARY_APPLIED = "URI_SUMMARY_APPLIED"
    URI_SUMMARY_LOADING = "URI_SUMMARY_LOADING"
    SUMMARY_IGNORED_NON_URI_WARNING = "SUMMARY_IGNORED_NON_URI_WARNING"
    HEAD_IGNORED_NON_URI_WARNING = "HEAD_IGNORED_NON_URI_WARNING"
    URI_HEAD_WITH_FORMAT_ERROR = "URI_HEAD_WITH_FORMAT_ERROR"
    URI_HEAD_WITH_SUMMARY_ERROR = "URI_HEAD_WITH_SUMMARY_ERROR"

    # Config / Collect
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CONFIG_PROMPT_CREATE = "CONFIG_PROMPT_CREATE"
    CONFIG_VIEW_TITLE = "CONFIG_VIEW_TITLE"
    CONFIG_SELECT_PROVIDER = "CONFIG_SELECT_PROVIDER"
    CONFIG_INPUT_BASE_URL = "CONFIG_INPUT_BASE_URL"
    CONFIG_INPUT_MODEL = "CONFIG_INPUT_MODEL"
    CONFIG_INPUT_API_KEY = "CONFIG_INPUT_API_KEY"
    CONFIG_INPUT_EXPORT_OUTPUT = "CONFIG_INPUT_EXPORT_OUTPUT"
    CONFIG_CONFIRM_TITLE = "CONFIG_CONFIRM_TITLE"
    CONFIG_CONFIRM_PROVIDER = "CONFIG_CONFIRM_PROVIDER"
    CONFIG_CONFIRM_BASE_URL = "CONFIG_CONFIRM_BASE_URL"
    CONFIG_CONFIRM_MODEL = "CONFIG_CONFIRM_MODEL"
    CONFIG_CONFIRM_API_KEY = "CONFIG_CONFIRM_API_KEY"
    CONFIG_CONFIRM_EXPORT_OUTPUT = "CONFIG_CONFIRM_EXPORT_OUTPUT"
    CONFIG_CONFIRM_WRITE = "CONFIG_CONFIRM_WRITE"
    CONFIG_CANCELLED = "CONFIG_CANCELLED"
    CONFIG_SAVED = "CONFIG_SAVED"
    CONFIG_ACTION_INVALID = "CONFIG_ACTION_INVALID"
    CONFIG_INVALID_FIELDS = "CONFIG_INVALID_FIELDS"
    CONFIG_INPUT_PROMPT = "CONFIG_INPUT_PROMPT"

    COLLECT_MODE_CONFLICT = "COLLECT_MODE_CONFLICT"
    COLLECT_DATE_FORMAT_INVALID = "COLLECT_DATE_FORMAT_INVALID"
    COLLECT_DATE_RANGE_INVALID = "COLLECT_DATE_RANGE_INVALID"
    COLLECT_CONFIG_MISSING = "COLLECT_CONFIG_MISSING"
    COLLECT_CONFIG_INCOMPLETE = "COLLECT_CONFIG_INCOMPLETE"
    COLLECT_CONFIG_HINT = "COLLECT_CONFIG_HINT"
    COLLECT_READ_FAILED = "COLLECT_READ_FAILED"
    COLLECT_NO_SESSIONS = "COLLECT_NO_SESSIONS"
    COLLECT_API_FAILED = "COLLECT_API_FAILED"
    COLLECT_OUTPUT_SAVED = "COLLECT_OUTPUT_SAVED"
    COLLECT_SUMMARY_LOADING = "COLLECT_SUMMARY_LOADING"
    COLLECT_SESSION_PROGRESS = "COLLECT_SESSION_PROGRESS"
    COLLECT_PROGRESS_START = "COLLECT_PROGRESS_START"
    COLLECT_PROGRESS_OVERVIEW = "COLLECT_PROGRESS_OVERVIEW"
    COLLECT_PROGRESS_AGENT_BREAKDOWN = "COLLECT_PROGRESS_AGENT_BREAKDOWN"
    COLLECT_PROGRESS_SCAN_SESSIONS = "COLLECT_PROGRESS_SCAN_SESSIONS"
    COLLECT_PROGRESS_PLAN_CHUNKS = "COLLECT_PROGRESS_PLAN_CHUNKS"
    COLLECT_PROGRESS_PLAN_CHUNKS_DONE = "COLLECT_PROGRESS_PLAN_CHUNKS_DONE"
    COLLECT_PROGRESS_SUMMARIZE_CHUNKS = "COLLECT_PROGRESS_SUMMARIZE_CHUNKS"
    COLLECT_PROGRESS_MERGE_SESSIONS = "COLLECT_PROGRESS_MERGE_SESSIONS"
    COLLECT_PROGRESS_TREE_REDUCTION = "COLLECT_PROGRESS_TREE_REDUCTION"
    COLLECT_PROGRESS_RENDER_FINAL = "COLLECT_PROGRESS_RENDER_FINAL"
    COLLECT_PROGRESS_WRITE_OUTPUT = "COLLECT_PROGRESS_WRITE_OUTPUT"
    SHORTCUT_MISSING_NAME = "SHORTCUT_MISSING_NAME"
    SHORTCUT_DATE_INVALID = "SHORTCUT_DATE_INVALID"
    SHORTCUT_TEMPLATE_INVALID = "SHORTCUT_TEMPLATE_INVALID"
    SHORTCUT_NOT_FOUND = "SHORTCUT_NOT_FOUND"
    SHORTCUT_ARGS_MISMATCH = "SHORTCUT_ARGS_MISMATCH"
    SHORTCUT_UNKNOWN_VARIABLE = "SHORTCUT_UNKNOWN_VARIABLE"
    DIAGNOSTIC_HEADER = "DIAGNOSTIC_HEADER"
    DIAGNOSTIC_SUMMARY = "DIAGNOSTIC_SUMMARY"
    DIAGNOSTIC_DETAILS = "DIAGNOSTIC_DETAILS"
    DIAGNOSTIC_SEARCHED_ROOTS = "DIAGNOSTIC_SEARCHED_ROOTS"
    DIAGNOSTIC_PARSED_URI = "DIAGNOSTIC_PARSED_URI"
    DIAGNOSTIC_CAPABILITY_GAP = "DIAGNOSTIC_CAPABILITY_GAP"
    DIAGNOSTIC_NEXT_STEPS = "DIAGNOSTIC_NEXT_STEPS"

    # Stats
    STATS_HEADER = "STATS_HEADER"
    STATS_TOTAL_SESSIONS = "STATS_TOTAL_SESSIONS"
    STATS_TOTAL_MESSAGES = "STATS_TOTAL_MESSAGES"
    STATS_BY_AGENT = "STATS_BY_AGENT"
    STATS_BY_TIME = "STATS_BY_TIME"
    STATS_NO_SESSIONS = "STATS_NO_SESSIONS"
    STATS_AGENT_ROW = "STATS_AGENT_ROW"
    STATS_TIME_ROW = "STATS_TIME_ROW"

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
        Keys.QUERY_INVALID: "❌ Invalid query: {error}",
        Keys.SUPPORTED_AGENTS: "\nSupported Agent Tools:",
        Keys.NO_AGENTS_IN_QUERY: "⚠️  No available Agent Tools in query scope.",
        Keys.LIST_HEADER_FILTERED: "📋 Listing sessions from last {days} days matching '{query}':\n",
        Keys.LIST_HEADER: "📋 Listing sessions from last {days} days:\n",
        Keys.NO_SESSIONS_IN_DAYS: "   (No sessions in last {days} days)",
        Keys.HINT_INTERACTIVE: "Hint: Use --interactive for interactive export mode",
        Keys.NO_SESSIONS_MATCHING_KEYWORD: "⚠️  No sessions found in last {days} days matching '{query}'.",
        Keys.AUTO_SELECT_AGENT: "Auto-selected: {agent_name}\n",
        Keys.NO_AGENT_SELECTED: "⚠️  No Agent Tool selected, exiting.",
        Keys.AGENT_SELECTED: "\nSelected: {agent_name}\n",
        Keys.NO_SESSIONS_FOUND: "⚠️  No sessions found in last {days} days.",
        Keys.SESSIONS_FOUND_FILTERED: "📊 Found {count} sessions (last {days} days, matching '{query}')\n",
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
        Keys.CLI_URI_HELP: "Agent session URI to dump, or agents://<path>?q=<keyword>&providers=<names>&roles=<names>&limit=<n> for scoped queries",
        Keys.CLI_DAYS_HELP: "Number of days to look back (default: 7)",
        Keys.CLI_OUTPUT_HELP: "Output base directory for JSON/raw exports (default: config export.output or ./sessions)",
        Keys.CLI_FORMAT_HELP: "Output format: json | markdown | raw | print (comma-separated, md alias supported)",
        Keys.CLI_HEAD_HELP: "Show lightweight session metadata for URI discovery without exporting or printing body",
        Keys.CLI_SUMMARY_HELP: "Generate AI summary for URI JSON export (requires config and json format)",
        Keys.CLI_LIST_HELP: "List all available sessions without exporting",
        Keys.CLI_INTERACTIVE_HELP: "Run in interactive mode to select and export sessions",
        Keys.CLI_NO_METADATA_SUMMARY_HELP: "Hide high-signal metadata summary in list and interactive views",
        Keys.CLI_SAVE_HELP: "Collect output path: directory or .md file path (absolute or relative)",
        Keys.CLI_PAGE_SIZE_HELP: "Number of sessions to display per page (default: 20)",
        Keys.CLI_QUERY_HELP: "Query filter. Supports legacy 'agent1,agent2:keyword' / 'keyword', or structured terms like 'bug provider:codex role:user path:. limit:20'; cannot be combined with agents:// query URIs",
        Keys.CLI_LANG_HELP: "Language (en, zh). Default: auto-detect",
        Keys.CLI_COLLECT_HELP: "Collect session prints by date range and summarize with AI",
        Keys.CLI_COLLECT_MODE_HELP: "Collect output mode: pm (project management) or insight (author insights)",
        Keys.CLI_SHORTCUT_HELP: "Run a configured shortcut preset",
        Keys.CLI_SINCE_HELP: "Collect start date (YYYY-MM-DD or YYYYMMDD)",
        Keys.CLI_UNTIL_HELP: "Collect end date (YYYY-MM-DD or YYYYMMDD)",
        Keys.CLI_CONFIG_HELP: "Manage AI config (view|edit)",
        Keys.CLI_STATS_HELP: "Show session usage statistics",
        Keys.CLI_SEARCH_HELP: "Full-text search keyword (searches message content via index)",
        Keys.CLI_REINDEX_HELP: "Force rebuild the full-text search index",
        Keys.CLI_VERSION_HELP: "Show version and exit (-v, --version)",
        Keys.CLI_FORMAT_INVALID: "invalid format list: {value}",
        Keys.SEARCH_INDEX_NOT_AVAILABLE: "⚠️  Full-text search is not available (SQLite FTS5 not supported).",
        Keys.REINDEX_START: "🔄 Rebuilding search index...",
        Keys.REINDEX_AGENT_DONE: "   ✓ {agent}: indexed {count} sessions",
        Keys.REINDEX_DONE: "✅ Index rebuild complete. Total indexed: {count} sessions.",
        Keys.LIST_IGNORE_FORMAT: "⚠️  --list mode ignores -format/--format.",
        Keys.LIST_IGNORE_OUTPUT: "⚠️  --list mode ignores -output/--output.",
        Keys.INTERACTIVE_FORMAT_INVALID: "❌ --interactive mode does not support print; use json, markdown, or raw.",
        Keys.URI_EXPORT_SAVED: "✅ Exported session [{format}] to: {path}",
        Keys.URI_SUMMARY_NO_JSON_WARNING: "⚠️  --summary requires json in --format; summary is skipped.",
        Keys.URI_SUMMARY_CONFIG_MISSING_WARNING: "⚠️  --summary skipped: config file not found.",
        Keys.URI_SUMMARY_CONFIG_INCOMPLETE_WARNING: "⚠️  --summary skipped: config missing fields: {fields}",
        Keys.URI_SUMMARY_API_FAILED_WARNING: "⚠️  --summary skipped: AI summary request failed: {error}",
        Keys.URI_SUMMARY_APPLIED: "✅ Applied summary to JSON: {path}",
        Keys.URI_SUMMARY_LOADING: "⏳ Calling AI to generate URI summary, please wait...",
        Keys.SUMMARY_IGNORED_NON_URI_WARNING: "⚠️  --summary is only supported in URI mode and will be ignored.",
        Keys.HEAD_IGNORED_NON_URI_WARNING: "⚠️  --head is only supported in URI mode and will be ignored.",
        Keys.URI_HEAD_WITH_FORMAT_ERROR: "❌ --head cannot be used with -format/--format.",
        Keys.URI_HEAD_WITH_SUMMARY_ERROR: "❌ --head cannot be used with --summary.",
        Keys.CONFIG_NOT_FOUND: "⚠️  Config file not found: {path}",
        Keys.CONFIG_PROMPT_CREATE: "Create config file now?",
        Keys.CONFIG_VIEW_TITLE: "Current config: {path}",
        Keys.CONFIG_SELECT_PROVIDER: "Select AI provider:",
        Keys.CONFIG_INPUT_BASE_URL: "Base URL",
        Keys.CONFIG_INPUT_MODEL: "Model",
        Keys.CONFIG_INPUT_API_KEY: "API Key",
        Keys.CONFIG_INPUT_EXPORT_OUTPUT: "Default export output",
        Keys.CONFIG_CONFIRM_TITLE: "\nPlease confirm config:",
        Keys.CONFIG_CONFIRM_PROVIDER: "  provider: {provider}",
        Keys.CONFIG_CONFIRM_BASE_URL: "  base_url: {base_url}",
        Keys.CONFIG_CONFIRM_MODEL: "  model: {model}",
        Keys.CONFIG_CONFIRM_API_KEY: "  api_key: {api_key}",
        Keys.CONFIG_CONFIRM_EXPORT_OUTPUT: "  export.output: {output}",
        Keys.CONFIG_CONFIRM_WRITE: "Write config file?",
        Keys.CONFIG_CANCELLED: "⚠️  Config update cancelled.",
        Keys.CONFIG_SAVED: "✅ Config saved: {path}",
        Keys.CONFIG_ACTION_INVALID: "❌ Invalid --config action: {action}",
        Keys.CONFIG_INVALID_FIELDS: "❌ Invalid config fields: {fields}",
        Keys.CONFIG_INPUT_PROMPT: "> ",
        Keys.COLLECT_MODE_CONFLICT: "❌ --collect cannot be used with URI/--interactive/--list.",
        Keys.COLLECT_DATE_FORMAT_INVALID: "❌ Invalid date format. Use YYYY-MM-DD or YYYYMMDD.",
        Keys.COLLECT_DATE_RANGE_INVALID: "❌ Invalid date range: since must be <= until.",
        Keys.COLLECT_CONFIG_MISSING: "❌ Collect requires config file.",
        Keys.COLLECT_CONFIG_INCOMPLETE: "❌ Collect config missing fields: {fields}",
        Keys.COLLECT_CONFIG_HINT: "Run: agent-dump -config edit",
        Keys.COLLECT_READ_FAILED: "❌ Failed to read sessions for collect: {error}",
        Keys.COLLECT_NO_SESSIONS: "⚠️  No sessions found in range {since} ~ {until}.",
        Keys.COLLECT_API_FAILED: "❌ AI summary request failed: {error}",
        Keys.COLLECT_OUTPUT_SAVED: "✅ Collect summary saved: {path}",
        Keys.COLLECT_SUMMARY_LOADING: "⏳ Calling AI to generate collect summary, please wait...",
        Keys.COLLECT_SESSION_PROGRESS: "session summaries: {completed}/{total} ({percent}%)",
        Keys.COLLECT_PROGRESS_START: "Collect started: {since} ~ {until}",
        Keys.COLLECT_PROGRESS_OVERVIEW: "Processing {session_count} sessions in total, split into {chunk_count} summary units; concurrency {concurrency}",
        Keys.COLLECT_PROGRESS_AGENT_BREAKDOWN: "Agent breakdown: {breakdown}",
        Keys.COLLECT_PROGRESS_SCAN_SESSIONS: "Scanning sessions: {current}/{total}",
        Keys.COLLECT_PROGRESS_PLAN_CHUNKS: "Preparing sessions: {current}/{total}",
        Keys.COLLECT_PROGRESS_PLAN_CHUNKS_DONE: "Preparation done: {session_count} sessions, {chunk_count} summary units",
        Keys.COLLECT_PROGRESS_SUMMARIZE_CHUNKS: "Summarizing content: {current}/{total} units done, concurrency {concurrency}",
        Keys.COLLECT_PROGRESS_MERGE_SESSIONS: "Merging session results: {current}/{total}",
        Keys.COLLECT_PROGRESS_TREE_REDUCTION: "Merging global result: round {level}, {current}/{total} groups",
        Keys.COLLECT_PROGRESS_RENDER_FINAL: "Generating final summary: {current}/{total}",
        Keys.COLLECT_PROGRESS_WRITE_OUTPUT: "Writing output file: {current}/{total}",
        Keys.SHORTCUT_MISSING_NAME: "❌ --shortcut requires a shortcut name.",
        Keys.SHORTCUT_DATE_INVALID: "❌ Invalid shortcut date value. Use YYYY-MM-DD or YYYYMMDD.",
        Keys.SHORTCUT_TEMPLATE_INVALID: "❌ Invalid shortcut template. format/conversion syntax is not supported.",
        Keys.SHORTCUT_NOT_FOUND: "❌ Shortcut not found: {name}",
        Keys.SHORTCUT_ARGS_MISMATCH: "❌ Shortcut {name} expects {expected} args, got {actual}.",
        Keys.SHORTCUT_UNKNOWN_VARIABLE: "❌ Shortcut template references unknown variable: {name}",
        Keys.DIAGNOSTIC_HEADER: "Diagnostic",
        Keys.DIAGNOSTIC_SUMMARY: "Summary",
        Keys.DIAGNOSTIC_DETAILS: "Details",
        Keys.DIAGNOSTIC_SEARCHED_ROOTS: "Searched roots",
        Keys.DIAGNOSTIC_PARSED_URI: "Parsed URI",
        Keys.DIAGNOSTIC_CAPABILITY_GAP: "Capability gap",
        Keys.DIAGNOSTIC_NEXT_STEPS: "Next steps",
        Keys.STATS_HEADER: "📊 Session Statistics (last {days} days)",
        Keys.STATS_TOTAL_SESSIONS: "Total sessions: {count}",
        Keys.STATS_TOTAL_MESSAGES: "Total messages: {count}",
        Keys.STATS_BY_AGENT: "By Agent",
        Keys.STATS_BY_TIME: "By Time",
        Keys.STATS_NO_SESSIONS: "No sessions found in the last {days} days.",
        Keys.STATS_AGENT_ROW: "  {name}: {sessions} sessions, {messages} messages",
        Keys.STATS_TIME_ROW: "  {label}: {count} sessions",
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
        Keys.QUERY_INVALID: "❌ 无效的查询条件: {error}",
        Keys.SUPPORTED_AGENTS: "\n支持的 Agent Tools:",
        Keys.NO_AGENTS_IN_QUERY: "⚠️  查询范围内没有可用的 Agent Tools。",
        Keys.LIST_HEADER_FILTERED: "📋 列出最近 {days} 天且匹配「{query}」的会话:\n",
        Keys.LIST_HEADER: "📋 列出最近 {days} 天的会话:\n",
        Keys.NO_SESSIONS_IN_DAYS: "   (最近 {days} 天内无会话)",
        Keys.HINT_INTERACTIVE: "提示: 使用 --interactive 进入交互式导出模式",
        Keys.NO_SESSIONS_MATCHING_KEYWORD: "⚠️  未找到最近 {days} 天内匹配「{query}」的会话。",
        Keys.AUTO_SELECT_AGENT: "自动选择: {agent_name}\n",
        Keys.NO_AGENT_SELECTED: "⚠️  未选择 Agent Tool，退出。",
        Keys.AGENT_SELECTED: "\n已选择: {agent_name}\n",
        Keys.NO_SESSIONS_FOUND: "⚠️  未找到最近 {days} 天内的会话。",
        Keys.SESSIONS_FOUND_FILTERED: "📊 找到 {count} 个会话 (最近 {days} 天，匹配「{query}」)\n",
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
        Keys.CLI_URI_HELP: "要导出的 Agent 会话 URI，或使用 agents://<path>?q=<关键词>&providers=<名称>&roles=<名称>&limit=<数量> 做路径作用域查询",
        Keys.CLI_DAYS_HELP: "查找最近几天的会话 (默认: 7)",
        Keys.CLI_OUTPUT_HELP: "JSON/raw 输出目录（默认: config export.output，其次 ./sessions）",
        Keys.CLI_FORMAT_HELP: "输出格式: json | markdown | raw | print（支持逗号分隔，兼容 md 别名）",
        Keys.CLI_HEAD_HELP: "仅查看 URI 会话的轻量元数据摘要，不导出文件也不打印正文",
        Keys.CLI_SUMMARY_HELP: "为 URI JSON 导出生成 AI 总结（需要配置且 format 包含 json）",
        Keys.CLI_LIST_HELP: "列出所有可用会话而不导出",
        Keys.CLI_QUERY_HELP: "查询过滤。兼容旧语法 'agent1,agent2:keyword' / 'keyword'，也支持结构化词项，如 'bug provider:codex role:user path:. limit:20'；不能与 agents:// 查询 URI 同时使用",
        Keys.CLI_INTERACTIVE_HELP: "进入交互式模式选择并导出",
        Keys.CLI_NO_METADATA_SUMMARY_HELP: "在列表和交互视图中隐藏高信号元数据摘要",
        Keys.CLI_SAVE_HELP: "collect 输出路径：可传目录或 .md 文件路径（支持绝对/相对路径）",
        Keys.CLI_PAGE_SIZE_HELP: "每页显示的会话数量 (默认: 20)",
        Keys.CLI_LANG_HELP: "语言 (en, zh). 默认: 自动检测",
        Keys.CLI_COLLECT_HELP: "按日期收集会话 print 内容并调用 AI 生成总结",
        Keys.CLI_COLLECT_MODE_HELP: "收集输出模式: pm（项目管理）或 insight（作者洞察）",
        Keys.CLI_SHORTCUT_HELP: "执行已配置的 shortcut 预设",
        Keys.CLI_SINCE_HELP: "收集开始日期 (YYYY-MM-DD 或 YYYYMMDD)",
        Keys.CLI_UNTIL_HELP: "收集结束日期 (YYYY-MM-DD 或 YYYYMMDD)",
        Keys.CLI_CONFIG_HELP: "管理 AI 配置 (view|edit)",
        Keys.CLI_STATS_HELP: "显示会话使用统计",
        Keys.CLI_SEARCH_HELP: "全文搜索关键词（通过索引搜索消息内容）",
        Keys.CLI_REINDEX_HELP: "强制重建全文搜索索引",
        Keys.CLI_VERSION_HELP: "显示版本号并退出（-v, --version）",
        Keys.CLI_FORMAT_INVALID: "无效的格式列表: {value}",
        Keys.SEARCH_INDEX_NOT_AVAILABLE: "⚠️  全文搜索不可用（SQLite 不支持 FTS5）。",
        Keys.REINDEX_START: "🔄 正在重建搜索索引...",
        Keys.REINDEX_AGENT_DONE: "   ✓ {agent}: 已索引 {count} 个会话",
        Keys.REINDEX_DONE: "✅ 索引重建完成。共索引 {count} 个会话。",
        Keys.LIST_IGNORE_FORMAT: "⚠️  --list 模式会忽略 -format/--format 参数。",
        Keys.LIST_IGNORE_OUTPUT: "⚠️  --list 模式会忽略 -output/--output 参数。",
        Keys.INTERACTIVE_FORMAT_INVALID: "❌ --interactive 模式不支持 print；可用格式为 json、markdown、raw。",
        Keys.URI_EXPORT_SAVED: "✅ 已导出 [{format}] 到: {path}",
        Keys.URI_SUMMARY_NO_JSON_WARNING: "⚠️  --summary 需要 --format 中包含 json；已跳过 summary。",
        Keys.URI_SUMMARY_CONFIG_MISSING_WARNING: "⚠️  已跳过 --summary：未找到配置文件。",
        Keys.URI_SUMMARY_CONFIG_INCOMPLETE_WARNING: "⚠️  已跳过 --summary：配置缺少字段: {fields}",
        Keys.URI_SUMMARY_API_FAILED_WARNING: "⚠️  已跳过 --summary：AI 总结请求失败: {error}",
        Keys.URI_SUMMARY_APPLIED: "✅ 已将 summary 写入 JSON: {path}",
        Keys.URI_SUMMARY_LOADING: "⏳ 正在调用 AI 生成会话总结，请稍候...",
        Keys.SUMMARY_IGNORED_NON_URI_WARNING: "⚠️  --summary 仅支持 URI 模式，当前已忽略。",
        Keys.HEAD_IGNORED_NON_URI_WARNING: "⚠️  --head 仅支持 URI 模式，当前已忽略。",
        Keys.URI_HEAD_WITH_FORMAT_ERROR: "❌ --head 不能与 -format/--format 同时使用。",
        Keys.URI_HEAD_WITH_SUMMARY_ERROR: "❌ --head 不能与 --summary 同时使用。",
        Keys.CONFIG_NOT_FOUND: "⚠️  未找到配置文件: {path}",
        Keys.CONFIG_PROMPT_CREATE: "现在创建配置文件吗？",
        Keys.CONFIG_VIEW_TITLE: "当前配置: {path}",
        Keys.CONFIG_SELECT_PROVIDER: "请选择 AI 提供商:",
        Keys.CONFIG_INPUT_BASE_URL: "Base URL",
        Keys.CONFIG_INPUT_MODEL: "Model",
        Keys.CONFIG_INPUT_API_KEY: "API Key",
        Keys.CONFIG_INPUT_EXPORT_OUTPUT: "默认导出目录",
        Keys.CONFIG_CONFIRM_TITLE: "\n请确认配置:",
        Keys.CONFIG_CONFIRM_PROVIDER: "  provider: {provider}",
        Keys.CONFIG_CONFIRM_BASE_URL: "  base_url: {base_url}",
        Keys.CONFIG_CONFIRM_MODEL: "  model: {model}",
        Keys.CONFIG_CONFIRM_API_KEY: "  api_key: {api_key}",
        Keys.CONFIG_CONFIRM_EXPORT_OUTPUT: "  export.output: {output}",
        Keys.CONFIG_CONFIRM_WRITE: "确认写入配置文件？",
        Keys.CONFIG_CANCELLED: "⚠️  已取消配置更新。",
        Keys.CONFIG_SAVED: "✅ 配置已保存: {path}",
        Keys.CONFIG_ACTION_INVALID: "❌ 无效的 --config 参数: {action}",
        Keys.CONFIG_INVALID_FIELDS: "❌ 配置项不完整: {fields}",
        Keys.CONFIG_INPUT_PROMPT: "> ",
        Keys.COLLECT_MODE_CONFLICT: "❌ --collect 不能与 URI/--interactive/--list 同时使用。",
        Keys.COLLECT_DATE_FORMAT_INVALID: "❌ 日期格式无效，请使用 YYYY-MM-DD 或 YYYYMMDD。",
        Keys.COLLECT_DATE_RANGE_INVALID: "❌ 日期区间无效，since 必须小于等于 until。",
        Keys.COLLECT_CONFIG_MISSING: "❌ collect 模式需要配置文件。",
        Keys.COLLECT_CONFIG_INCOMPLETE: "❌ collect 配置缺少字段: {fields}",
        Keys.COLLECT_CONFIG_HINT: "请先执行: agent-dump -config edit",
        Keys.COLLECT_READ_FAILED: "❌ collect 读取会话失败: {error}",
        Keys.COLLECT_NO_SESSIONS: "⚠️  在 {since} ~ {until} 区间内未找到会话。",
        Keys.COLLECT_API_FAILED: "❌ AI 总结请求失败: {error}",
        Keys.COLLECT_OUTPUT_SAVED: "✅ collect 总结已保存: {path}",
        Keys.COLLECT_SUMMARY_LOADING: "⏳ 正在调用 AI 生成汇总，请稍候...",
        Keys.COLLECT_SESSION_PROGRESS: "session summaries: {completed}/{total} ({percent}%)",
        Keys.COLLECT_PROGRESS_START: "Collect 任务开始：{since} ~ {until}",
        Keys.COLLECT_PROGRESS_OVERVIEW: "本次将处理 {session_count} 个 session，拆分为 {chunk_count} 个总结单元；并发 {concurrency}",
        Keys.COLLECT_PROGRESS_AGENT_BREAKDOWN: "Agent 分布：{breakdown}",
        Keys.COLLECT_PROGRESS_SCAN_SESSIONS: "正在扫描会话：{current}/{total}",
        Keys.COLLECT_PROGRESS_PLAN_CHUNKS: "正在预处理会话：{current}/{total}",
        Keys.COLLECT_PROGRESS_PLAN_CHUNKS_DONE: "已完成预处理：{session_count} 个 session，拆分为 {chunk_count} 个总结单元",
        Keys.COLLECT_PROGRESS_SUMMARIZE_CHUNKS: "正在总结内容：已完成 {current}/{total} 个单元，并发 {concurrency}",
        Keys.COLLECT_PROGRESS_MERGE_SESSIONS: "正在合并 session 结果：{current}/{total}",
        Keys.COLLECT_PROGRESS_TREE_REDUCTION: "正在归并全局结果：第 {level} 轮，{current}/{total} 组",
        Keys.COLLECT_PROGRESS_RENDER_FINAL: "正在生成最终总结：{current}/{total}",
        Keys.COLLECT_PROGRESS_WRITE_OUTPUT: "正在写入结果文件：{current}/{total}",
        Keys.SHORTCUT_MISSING_NAME: "❌ --shortcut 需要提供快捷方式名称。",
        Keys.SHORTCUT_DATE_INVALID: "❌ shortcut 中的 date 参数格式无效，请使用 YYYY-MM-DD 或 YYYYMMDD。",
        Keys.SHORTCUT_TEMPLATE_INVALID: "❌ shortcut 模板无效，暂不支持 format/conversion 语法。",
        Keys.SHORTCUT_NOT_FOUND: "❌ 未找到 shortcut: {name}",
        Keys.SHORTCUT_ARGS_MISMATCH: "❌ shortcut {name} 参数数量不匹配，期望 {expected} 个，实际 {actual} 个。",
        Keys.SHORTCUT_UNKNOWN_VARIABLE: "❌ shortcut 模板引用了未定义变量: {name}",
        Keys.DIAGNOSTIC_HEADER: "诊断信息",
        Keys.DIAGNOSTIC_SUMMARY: "结论",
        Keys.DIAGNOSTIC_DETAILS: "证据",
        Keys.DIAGNOSTIC_SEARCHED_ROOTS: "searched roots",
        Keys.DIAGNOSTIC_PARSED_URI: "解析后的 URI",
        Keys.DIAGNOSTIC_CAPABILITY_GAP: "缺失能力",
        Keys.DIAGNOSTIC_NEXT_STEPS: "下一步",
        Keys.STATS_HEADER: "📊 会话统计 (最近 {days} 天)",
        Keys.STATS_TOTAL_SESSIONS: "总会话数: {count}",
        Keys.STATS_TOTAL_MESSAGES: "总消息数: {count}",
        Keys.STATS_BY_AGENT: "按 Agent",
        Keys.STATS_BY_TIME: "按时间",
        Keys.STATS_NO_SESSIONS: "最近 {days} 天内未找到会话。",
        Keys.STATS_AGENT_ROW: "  {name}: {sessions} 个会话, {messages} 条消息",
        Keys.STATS_TIME_ROW: "  {label}: {count} 个会话",
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
