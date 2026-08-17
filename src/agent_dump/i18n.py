"""
Internationalization support for agent-dump
"""

import locale
import os


# Translation keys
class Keys:
    NO_AGENTS_FOUND = "NO_AGENTS_FOUND"
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
    CLI_DRY_RUN_HELP = "CLI_DRY_RUN_HELP"
    CLI_SHORTCUT_HELP = "CLI_SHORTCUT_HELP"
    CLI_SINCE_HELP = "CLI_SINCE_HELP"
    CLI_UNTIL_HELP = "CLI_UNTIL_HELP"
    CLI_CONFIG_HELP = "CLI_CONFIG_HELP"
    CLI_STATS_HELP = "CLI_STATS_HELP"
    CLI_SEARCH_HELP = "CLI_SEARCH_HELP"
    CLI_REINDEX_HELP = "CLI_REINDEX_HELP"
    CLI_PROVIDERS_HELP = "CLI_PROVIDERS_HELP"
    CLI_VERSION_HELP = "CLI_VERSION_HELP"
    CLI_FORMAT_INVALID = "CLI_FORMAT_INVALID"
    CLI_DAYS_INVALID = "CLI_DAYS_INVALID"
    SEARCH_INDEX_NOT_AVAILABLE = "SEARCH_INDEX_NOT_AVAILABLE"
    SEARCH_HEADER = "SEARCH_HEADER"
    SEARCH_NO_RESULTS = "SEARCH_NO_RESULTS"
    SEARCH_RESULT_PROVIDER = "SEARCH_RESULT_PROVIDER"
    SEARCH_RESULT_UPDATED = "SEARCH_RESULT_UPDATED"
    SEARCH_RESULT_URI = "SEARCH_RESULT_URI"
    SEARCH_RESULT_RANK = "SEARCH_RESULT_RANK"
    SEARCH_RESULT_SNIPPET = "SEARCH_RESULT_SNIPPET"
    REINDEX_START = "REINDEX_START"
    REINDEX_AGENT_DONE = "REINDEX_AGENT_DONE"
    REINDEX_DONE = "REINDEX_DONE"
    PROVIDERS_HEADER = "PROVIDERS_HEADER"
    PROVIDERS_TABLE_HEADER = "PROVIDERS_TABLE_HEADER"
    PROVIDERS_ROW = "PROVIDERS_ROW"
    PROVIDERS_YES = "PROVIDERS_YES"
    PROVIDERS_NO = "PROVIDERS_NO"
    PROVIDERS_NONE = "PROVIDERS_NONE"
    PROVIDERS_ROOT_COUNT = "PROVIDERS_ROOT_COUNT"
    PROVIDERS_SEARCH_ROOTS = "PROVIDERS_SEARCH_ROOTS"
    PROVIDERS_ROOT_NONE = "PROVIDERS_ROOT_NONE"
    PROVIDERS_ROOT_EXISTS = "PROVIDERS_ROOT_EXISTS"
    PROVIDERS_ROOT_MISSING = "PROVIDERS_ROOT_MISSING"
    PROVIDERS_ROOT_ROW = "PROVIDERS_ROOT_ROW"
    LIST_IGNORE_FORMAT = "LIST_IGNORE_FORMAT"
    LIST_IGNORE_OUTPUT = "LIST_IGNORE_OUTPUT"
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
    COLLECT_CONFIG_BAD_SCHEME = "COLLECT_CONFIG_BAD_SCHEME"
    COLLECT_CONFIG_PLAINTEXT_KEY = "COLLECT_CONFIG_PLAINTEXT_KEY"
    COLLECT_READ_FAILED = "COLLECT_READ_FAILED"
    COLLECT_NO_SESSIONS = "COLLECT_NO_SESSIONS"
    COLLECT_API_FAILED = "COLLECT_API_FAILED"
    COLLECT_OUTPUT_SAVED = "COLLECT_OUTPUT_SAVED"
    COLLECT_DRY_RUN_HEADER = "COLLECT_DRY_RUN_HEADER"
    COLLECT_DRY_RUN_DATE_RANGE = "COLLECT_DRY_RUN_DATE_RANGE"
    COLLECT_DRY_RUN_PROVIDER_BREAKDOWN = "COLLECT_DRY_RUN_PROVIDER_BREAKDOWN"
    COLLECT_DRY_RUN_SESSION_COUNT = "COLLECT_DRY_RUN_SESSION_COUNT"
    COLLECT_DRY_RUN_CHUNK_COUNT = "COLLECT_DRY_RUN_CHUNK_COUNT"
    COLLECT_DRY_RUN_CONCURRENCY = "COLLECT_DRY_RUN_CONCURRENCY"
    COLLECT_DRY_RUN_SAVE_PATH = "COLLECT_DRY_RUN_SAVE_PATH"
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

    # provider / 运行时告警（AD-138）
    WARN_SESSION_LOOKUP_FAILED = "WARN_SESSION_LOOKUP_FAILED"
    WARN_PROVIDER_OPERATION_FAILED = "WARN_PROVIDER_OPERATION_FAILED"
    WARN_SESSION_PARSE_FAILED = "WARN_SESSION_PARSE_FAILED"
    WARN_TITLE_CACHE_FAILED = "WARN_TITLE_CACHE_FAILED"
    WARN_TITLE_EXTRACT_FAILED = "WARN_TITLE_EXTRACT_FAILED"
    WARN_MESSAGE_CONVERT_FAILED = "WARN_MESSAGE_CONVERT_FAILED"
    WARN_CONTEXT_CONVERT_FAILED = "WARN_CONTEXT_CONVERT_FAILED"
    WARN_WIRE_CONVERT_FAILED = "WARN_WIRE_CONVERT_FAILED"
    WARN_PI_RECORD_CONVERT_FAILED = "WARN_PI_RECORD_CONVERT_FAILED"
    WARN_MESSAGE_DATA_PARSE_FAILED = "WARN_MESSAGE_DATA_PARSE_FAILED"
    WARN_PART_DATA_PARSE_FAILED = "WARN_PART_DATA_PARSE_FAILED"
    WARN_INSECURE_BASE_URL = "WARN_INSECURE_BASE_URL"

    # 诊断 summary / next_steps（AD-138）
    DIAG_SESSION_NOT_FOUND = "DIAG_SESSION_NOT_FOUND"
    DIAG_UNEXPECTED_FAILURE = "DIAG_UNEXPECTED_FAILURE"
    DIAG_STEP_RETRY_ONCE = "DIAG_STEP_RETRY_ONCE"
    DIAG_STEP_FILE_ISSUE = "DIAG_STEP_FILE_ISSUE"
    DIAG_STEP_PICK_ANOTHER_SESSION = "DIAG_STEP_PICK_ANOTHER_SESSION"
    DIAG_URI_CAPABILITY_GAP = "DIAG_URI_CAPABILITY_GAP"
    DIAG_URI_CAPABILITY_DETAIL = "DIAG_URI_CAPABILITY_DETAIL"
    DIAG_STEP_DROP_FORMATS = "DIAG_STEP_DROP_FORMATS"
    DIAG_STEP_EXPORT_JSON_FIRST = "DIAG_STEP_EXPORT_JSON_FIRST"
    DIAG_NO_LOCAL_SESSIONS = "DIAG_NO_LOCAL_SESSIONS"
    DIAG_STEP_CHECK_AGENT_DATA = "DIAG_STEP_CHECK_AGENT_DATA"
    DIAG_STEP_CHECK_ENV_VARS = "DIAG_STEP_CHECK_ENV_VARS"
    DIAG_STEP_CHECK_DEV_FALLBACK = "DIAG_STEP_CHECK_DEV_FALLBACK"
    DIAG_SESSION_READ_FAILED = "DIAG_SESSION_READ_FAILED"
    DIAG_STEP_CHECK_LOCAL_SOURCE = "DIAG_STEP_CHECK_LOCAL_SOURCE"
    DIAG_STEP_NARROW_WITH_LIST = "DIAG_STEP_NARROW_WITH_LIST"
    DIAG_URI_INVALID = "DIAG_URI_INVALID"
    DIAG_URI_UNPARSEABLE = "DIAG_URI_UNPARSEABLE"
    DIAG_STEP_USE_SUPPORTED_SCHEME = "DIAG_STEP_USE_SUPPORTED_SCHEME"
    DIAG_URI_SCANNED_NO_MATCH = "DIAG_URI_SCANNED_NO_MATCH"
    DIAG_STEP_LIST_TO_CONFIRM = "DIAG_STEP_LIST_TO_CONFIRM"
    DIAG_STEP_CHECK_URI_SESSION_ID = "DIAG_STEP_CHECK_URI_SESSION_ID"
    DIAG_URI_SCHEME_MISMATCH = "DIAG_URI_SCHEME_MISMATCH"
    DIAG_URI_BELONGS_TO = "DIAG_URI_BELONGS_TO"
    DIAG_STEP_USE_THIS_URI = "DIAG_STEP_USE_THIS_URI"
    DIAG_QUERY_URI_INVALID = "DIAG_QUERY_URI_INVALID"
    DIAG_STEP_CHECK_QUERY_URI_SHAPE = "DIAG_STEP_CHECK_QUERY_URI_SHAPE"
    DIAG_STEP_NO_QUERY_URI_WITH_Q = "DIAG_STEP_NO_QUERY_URI_WITH_Q"
    DIAG_QUERY_COMBINATION_INVALID = "DIAG_QUERY_COMBINATION_INVALID"
    DIAG_QUERY_URI_WITH_Q_DETAIL = "DIAG_QUERY_URI_WITH_Q_DETAIL"
    DIAG_STEP_DROP_Q = "DIAG_STEP_DROP_Q"
    DIAG_PRINT_UNSUPPORTED_MODE = "DIAG_PRINT_UNSUPPORTED_MODE"
    DIAG_PRINT_UNSUPPORTED_DETAIL = "DIAG_PRINT_UNSUPPORTED_DETAIL"
    DIAG_STEP_DROP_PRINT = "DIAG_STEP_DROP_PRINT"
    DIAG_QUERY_SPEC_INVALID = "DIAG_QUERY_SPEC_INVALID"
    DIAG_STEP_QUERY_FORMAT = "DIAG_STEP_QUERY_FORMAT"
    DIAG_STEP_QUERY_URI_FOR_PATH = "DIAG_STEP_QUERY_URI_FOR_PATH"
    DIAG_NO_PROVIDER_IN_SCOPE = "DIAG_NO_PROVIDER_IN_SCOPE"
    DIAG_STEP_CONFIRM_PROVIDERS_HAVE_DATA = "DIAG_STEP_CONFIRM_PROVIDERS_HAVE_DATA"
    DIAG_STEP_WIDEN_PROVIDERS = "DIAG_STEP_WIDEN_PROVIDERS"
    INDEX_UPDATE_PROGRESS = "INDEX_UPDATE_PROGRESS"
    WARN_INDEX_SKIPPED_SESSIONS = "WARN_INDEX_SKIPPED_SESSIONS"
    WARN_JSONL_RECORDS_SKIPPED = "WARN_JSONL_RECORDS_SKIPPED"
    WARN_INDEX_UNUSABLE = "WARN_INDEX_UNUSABLE"
    WARN_SESSION_SUMMARY_SKIPPED = "WARN_SESSION_SUMMARY_SKIPPED"
    WARN_SESSION_SUMMARY_FAILURES = "WARN_SESSION_SUMMARY_FAILURES"

    # provider 专属诊断的 next_steps（AD-146）
    DIAG_STEP_RAW_SOURCE_LOCAL = "DIAG_STEP_RAW_SOURCE_LOCAL"
    DIAG_STEP_LIST_TO_CHECK_VISIBLE = "DIAG_STEP_LIST_TO_CHECK_VISIBLE"
    DIAG_STEP_USE_JSON_OR_MARKDOWN = "DIAG_STEP_USE_JSON_OR_MARKDOWN"
    DIAG_STEP_CHECK_PROVIDER_HAS_RAW = "DIAG_STEP_CHECK_PROVIDER_HAS_RAW"
    DIAG_STEP_CODEX_SESSION_LOCATION = "DIAG_STEP_CODEX_SESSION_LOCATION"
    DIAG_STEP_LIST_TO_CHECK_ID = "DIAG_STEP_LIST_TO_CHECK_ID"
    DIAG_STEP_CLAUDE_SESSION_LOCATION = "DIAG_STEP_CLAUDE_SESSION_LOCATION"
    DIAG_STEP_LIST_TO_CHECK_EXISTS = "DIAG_STEP_LIST_TO_CHECK_EXISTS"
    DIAG_STEP_KIMI_NEEDS_JSONL = "DIAG_STEP_KIMI_NEEDS_JSONL"
    DIAG_STEP_READABLE_EXPORT_INSTEAD = "DIAG_STEP_READABLE_EXPORT_INSTEAD"
    DIAG_STEP_KIMI_SOURCE_INTACT = "DIAG_STEP_KIMI_SOURCE_INTACT"
    DIAG_STEP_KIMI_CONTEXT_INTACT = "DIAG_STEP_KIMI_CONTEXT_INTACT"
    DIAG_STEP_KIMI_WIRE_FALLBACK = "DIAG_STEP_KIMI_WIRE_FALLBACK"
    DIAG_STEP_KIMI_WIRE_INTACT = "DIAG_STEP_KIMI_WIRE_INTACT"
    DIAG_STEP_KIMI_CONTEXT_FALLBACK = "DIAG_STEP_KIMI_CONTEXT_FALLBACK"
    DIAG_STEP_PI_SESSION_LOCATION = "DIAG_STEP_PI_SESSION_LOCATION"
    DIAG_STEP_CURSOR_DB_EXISTS = "DIAG_STEP_CURSOR_DB_EXISTS"
    DIAG_STEP_CURSOR_LIST_TO_CHECK = "DIAG_STEP_CURSOR_LIST_TO_CHECK"
    DIAG_STEP_USE_JSON_OR_PRINT = "DIAG_STEP_USE_JSON_OR_PRINT"
    DIAG_STEP_CURSOR_INSPECT_SQLITE = "DIAG_STEP_CURSOR_INSPECT_SQLITE"
    DIAG_STEP_OPENCODE_DB_EXISTS = "DIAG_STEP_OPENCODE_DB_EXISTS"
    DIAG_STEP_OPENCODE_DEV_DB = "DIAG_STEP_OPENCODE_DEV_DB"
    DIAG_STEP_ZCODE_DB_EXISTS = "DIAG_STEP_ZCODE_DB_EXISTS"
    DIAG_STEP_ZCODE_DB_PATHS = "DIAG_STEP_ZCODE_DB_PATHS"
    DIAG_STEP_ZCODE_NO_LINUX = "DIAG_STEP_ZCODE_NO_LINUX"

    # 查询摘要 / 查询解析错误 / patch 解析错误（AD-146 追加）
    QUERY_SUMMARY_PATH = "QUERY_SUMMARY_PATH"
    QUERY_SUMMARY_KEYWORD = "QUERY_SUMMARY_KEYWORD"
    QUERY_SUMMARY_ALL_SESSIONS = "QUERY_SUMMARY_ALL_SESSIONS"
    QUERY_ERROR_EMPTY_SPEC = "QUERY_ERROR_EMPTY_SPEC"
    QUERY_ERROR_UNKNOWN_AGENT = "QUERY_ERROR_UNKNOWN_AGENT"
    QUERY_ERROR_EMPTY_KEYWORD = "QUERY_ERROR_EMPTY_KEYWORD"
    QUERY_ERROR_EMPTY_PATH = "QUERY_ERROR_EMPTY_PATH"
    QUERY_ERROR_EMPTY_PROVIDERS = "QUERY_ERROR_EMPTY_PROVIDERS"
    QUERY_ERROR_EMPTY_ROLES = "QUERY_ERROR_EMPTY_ROLES"
    QUERY_ERROR_EMPTY_LIMIT = "QUERY_ERROR_EMPTY_LIMIT"
    QUERY_ERROR_LIMIT_NOT_POSITIVE = "QUERY_ERROR_LIMIT_NOT_POSITIVE"
    QUERY_ERROR_LIMIT_TOO_LARGE = "QUERY_ERROR_LIMIT_TOO_LARGE"
    QUERY_ERROR_UNKNOWN_FIELD = "QUERY_ERROR_UNKNOWN_FIELD"
    QUERY_ERROR_DUPLICATE_PATH = "QUERY_ERROR_DUPLICATE_PATH"
    QUERY_ERROR_DUPLICATE_LIMIT = "QUERY_ERROR_DUPLICATE_LIMIT"
    PATCH_ERROR_EMPTY = "PATCH_ERROR_EMPTY"
    PATCH_ERROR_MISSING_HEADER = "PATCH_ERROR_MISSING_HEADER"
    PATCH_ERROR_MISSING_FOOTER = "PATCH_ERROR_MISSING_FOOTER"
    PATCH_ERROR_BAD_OPERATION = "PATCH_ERROR_BAD_OPERATION"
    PATCH_ERROR_BAD_LINE = "PATCH_ERROR_BAD_LINE"
    GROUP_HEADER_DISABLED_HINT = "GROUP_HEADER_DISABLED_HINT"
    DIAGNOSTIC_PARSED_URI = "DIAGNOSTIC_PARSED_URI"
    DIAGNOSTIC_CAPABILITY_GAP = "DIAGNOSTIC_CAPABILITY_GAP"
    DIAGNOSTIC_NEXT_STEPS = "DIAGNOSTIC_NEXT_STEPS"

    # Stats
    STATS_HEADER = "STATS_HEADER"
    STATS_TOTAL_SESSIONS = "STATS_TOTAL_SESSIONS"
    STATS_TOTAL_MESSAGES = "STATS_TOTAL_MESSAGES"
    STATS_KNOWN_MESSAGES = "STATS_KNOWN_MESSAGES"
    STATS_BY_AGENT = "STATS_BY_AGENT"
    STATS_BY_TIME = "STATS_BY_TIME"
    STATS_NO_SESSIONS = "STATS_NO_SESSIONS"
    STATS_AGENT_ROW = "STATS_AGENT_ROW"
    STATS_AGENT_ROW_WITH_UNKNOWN = "STATS_AGENT_ROW_WITH_UNKNOWN"
    STATS_TIME_ROW = "STATS_TIME_ROW"
    MESSAGE_COUNT_UNKNOWN = "MESSAGE_COUNT_UNKNOWN"

    # Misc
    SESSION_COUNT_SUFFIX = "SESSION_COUNT_SUFFIX"


TRANSLATIONS = {
    "en": {
        Keys.NO_AGENTS_FOUND: "❌ No available Agent Tools sessions found.",
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
        Keys.SCANNING_AGENTS: "🔍 Scanning Agent Tools...\n",
        Keys.AGENT_FOUND: "   ✓ Found {name} ({count} sessions)",
        Keys.AGENT_FOUND_EMPTY: "   ⚠ Found {name} (0 sessions)",
        Keys.TIME_TODAY: "Today",
        Keys.TIME_YESTERDAY: "Yesterday",
        Keys.TIME_THIS_WEEK: "This Week",
        Keys.TIME_THIS_MONTH: "This Month",
        Keys.TIME_OLDER: "Older",
        Keys.TIME_UNKNOWN: "Unknown Time",
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
        Keys.CLI_DAYS_HELP: "Lookback days (default: 7; collect defaults to today unless specified)",
        Keys.CLI_OUTPUT_HELP: "Output base directory for JSON/raw exports (default: config export.output or ./sessions)",
        Keys.CLI_FORMAT_HELP: "Output format: json | markdown | raw | print (comma-separated, md alias supported)",
        Keys.CLI_HEAD_HELP: "Show lightweight session metadata for URI discovery without exporting or printing body",
        Keys.CLI_SUMMARY_HELP: "Generate AI summary for URI JSON export (requires config and json format)",
        Keys.CLI_LIST_HELP: "List all available sessions without exporting",
        Keys.CLI_INTERACTIVE_HELP: "Run in interactive mode to select and export sessions",
        Keys.CLI_NO_METADATA_SUMMARY_HELP: "Hide high-signal metadata summary in list and interactive views",
        Keys.CLI_SAVE_HELP: "Collect output path: directory or .md file path (absolute or relative)",
        Keys.CLI_PAGE_SIZE_HELP: "Accepted for compatibility; currently ignored",
        Keys.CLI_QUERY_HELP: "Query filter. Supports legacy 'agent1,agent2:keyword' / 'keyword', or structured terms like 'bug provider:codex role:user path:. limit:20'; cannot be combined with agents:// query URIs",
        Keys.CLI_LANG_HELP: "Language (en, zh). Default: auto-detect",
        Keys.CLI_COLLECT_HELP: "Collect session prints by date range and summarize with AI",
        Keys.CLI_COLLECT_MODE_HELP: "Collect output mode: pm (project management) or insight (author insights)",
        Keys.CLI_DRY_RUN_HELP: "Preview collect workload without AI calls or file writes",
        Keys.CLI_SHORTCUT_HELP: "Run a configured shortcut preset",
        Keys.CLI_SINCE_HELP: "Collect start date (YYYY-MM-DD or YYYYMMDD)",
        Keys.CLI_UNTIL_HELP: "Collect end date (YYYY-MM-DD or YYYYMMDD)",
        Keys.CLI_CONFIG_HELP: "Manage AI config (view|edit)",
        Keys.CLI_STATS_HELP: "Show session usage statistics",
        Keys.CLI_SEARCH_HELP: "Full-text search keyword (searches message content via index)",
        Keys.CLI_REINDEX_HELP: "Force rebuild the full-text search index",
        Keys.CLI_PROVIDERS_HELP: "Show provider capabilities and local search roots",
        Keys.CLI_VERSION_HELP: "Show version and exit (-v, --version)",
        Keys.CLI_FORMAT_INVALID: "invalid format list: {value}",
        Keys.CLI_DAYS_INVALID: "invalid lookback days: {value}; expected a positive value within the calendar range",
        Keys.SEARCH_INDEX_NOT_AVAILABLE: "⚠️  Full-text search is not available (SQLite FTS5 not supported).",
        Keys.SEARCH_HEADER: "🔎 Search results from last {days} days matching '{query}':\n",
        Keys.SEARCH_NO_RESULTS: "   (No search results)",
        Keys.SEARCH_RESULT_PROVIDER: "Provider",
        Keys.SEARCH_RESULT_UPDATED: "Updated",
        Keys.SEARCH_RESULT_URI: "URI",
        Keys.SEARCH_RESULT_RANK: "Rank",
        Keys.SEARCH_RESULT_SNIPPET: "Snippet",
        Keys.REINDEX_START: "🔄 Rebuilding search index...",
        Keys.REINDEX_AGENT_DONE: "   ✓ {agent}: indexed {count} sessions",
        Keys.REINDEX_DONE: "✅ Index rebuild complete. Total indexed: {count} sessions.",
        Keys.PROVIDERS_HEADER: "Provider capabilities",
        Keys.PROVIDERS_TABLE_HEADER: "Provider | URI | Formats | Keyword fast path | Search roots | Unsupported",
        Keys.PROVIDERS_ROW: "{provider} | {uri} | {formats} | {keyword} | {roots} | {unsupported}",
        Keys.PROVIDERS_YES: "yes",
        Keys.PROVIDERS_NO: "no",
        Keys.PROVIDERS_NONE: "none",
        Keys.PROVIDERS_ROOT_COUNT: "{existing}/{total} found",
        Keys.PROVIDERS_SEARCH_ROOTS: "Search roots",
        Keys.PROVIDERS_ROOT_NONE: "  - [unavailable] no default path on this platform",
        Keys.PROVIDERS_ROOT_EXISTS: "found",
        Keys.PROVIDERS_ROOT_MISSING: "missing",
        Keys.PROVIDERS_ROOT_ROW: "  - [{status}] {label}: {path}",
        Keys.LIST_IGNORE_FORMAT: "⚠️  --list mode ignores -format/--format.",
        Keys.LIST_IGNORE_OUTPUT: "⚠️  --list mode ignores -output/--output.",
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
        Keys.COLLECT_CONFIG_BAD_SCHEME: "❌ ai.base_url must use http or https.",
        Keys.COLLECT_CONFIG_PLAINTEXT_KEY: (
            "❌ ai.base_url uses http, which would send api_key in cleartext. "
            "Use https, or point base_url at localhost."
        ),
        Keys.COLLECT_READ_FAILED: "❌ Failed to read sessions for collect: {error}",
        Keys.COLLECT_NO_SESSIONS: "⚠️  No sessions found in range {since} ~ {until}.",
        Keys.COLLECT_API_FAILED: "❌ AI summary request failed: {error}",
        Keys.COLLECT_OUTPUT_SAVED: "✅ Collect summary saved: {path}",
        Keys.COLLECT_DRY_RUN_HEADER: "Collect dry-run preview",
        Keys.COLLECT_DRY_RUN_DATE_RANGE: "Date range: {since} ~ {until}",
        Keys.COLLECT_DRY_RUN_PROVIDER_BREAKDOWN: "Provider breakdown: {breakdown}",
        Keys.COLLECT_DRY_RUN_SESSION_COUNT: "Sessions: {count}",
        Keys.COLLECT_DRY_RUN_CHUNK_COUNT: "Chunks: {count}",
        Keys.COLLECT_DRY_RUN_CONCURRENCY: "Concurrency: {concurrency}",
        Keys.COLLECT_DRY_RUN_SAVE_PATH: "Save path: {path}",
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
        Keys.WARN_SESSION_LOOKUP_FAILED: "⚠️  {agent} session lookup failed: {error}",
        Keys.WARN_PROVIDER_OPERATION_FAILED: "⚠️  {agent} provider operation failed: {error_type}: {error}",
        Keys.WARN_SESSION_PARSE_FAILED: "⚠️  Failed to parse session file {path}: {error}",
        Keys.WARN_TITLE_CACHE_FAILED: "⚠️  Failed to load title cache: {error}",
        Keys.WARN_TITLE_EXTRACT_FAILED: "⚠️  Failed to extract title: {error}",
        Keys.WARN_MESSAGE_CONVERT_FAILED: "⚠️  Failed to convert message format: {error}",
        Keys.WARN_CONTEXT_CONVERT_FAILED: "⚠️  Failed to convert context record: {error}",
        Keys.WARN_WIRE_CONVERT_FAILED: "⚠️  Failed to convert wire record: {error}",
        Keys.WARN_PI_RECORD_CONVERT_FAILED: "⚠️  Failed to convert Pi record: {error}",
        Keys.WARN_MESSAGE_DATA_PARSE_FAILED: "⚠️  Failed to parse message data message={message_id}",
        Keys.WARN_PART_DATA_PARSE_FAILED: "⚠️  Failed to parse message part data part={part_id}",
        Keys.WARN_INSECURE_BASE_URL: "⚠️  AI base_url is not HTTPS; api_key may be sent in cleartext.",
        Keys.DIAG_SESSION_NOT_FOUND: "No matching session found.",
        Keys.DIAG_UNEXPECTED_FAILURE: "Command aborted with an unexpected error.",
        Keys.DIAG_STEP_RETRY_ONCE: "Retry once to check whether the failure is transient.",
        Keys.DIAG_STEP_FILE_ISSUE: "If it reproduces consistently, open an issue with the error type above and your command arguments.",
        Keys.DIAG_STEP_PICK_ANOTHER_SESSION: "Pick another session, or fix the session id in the provider data.",
        Keys.DIAG_URI_CAPABILITY_GAP: "The current URI requested an export capability {agent} does not support.",
        Keys.DIAG_URI_CAPABILITY_DETAIL: "{agent} URI supports only {supported}; requested {requested}",
        Keys.DIAG_STEP_DROP_FORMATS: "Remove {formats} and use a supported format.",
        Keys.DIAG_STEP_EXPORT_JSON_FIRST: "For further processing, export JSON first and convert afterwards.",
        Keys.DIAG_NO_LOCAL_SESSIONS: "No usable local session data found.",
        Keys.DIAG_STEP_CHECK_AGENT_DATA: "Confirm the agent has produced session data on this machine.",
        Keys.DIAG_STEP_CHECK_ENV_VARS: "If you use a custom directory, check that the relevant environment variable points at it.",
        Keys.DIAG_STEP_CHECK_DEV_FALLBACK: "In a development environment, check whether the `data/<agent>` fallback directory exists.",
        Keys.DIAG_SESSION_READ_FAILED: "Failed to read session data.",
        Keys.DIAG_STEP_CHECK_LOCAL_SOURCE: "Check whether the local session source file or database still exists.",
        Keys.DIAG_STEP_NARROW_WITH_LIST: "If it persists, narrow the scope with `agent-dump --list` and retry.",
        Keys.DIAG_URI_INVALID: "Invalid URI format.",
        Keys.DIAG_URI_UNPARSEABLE: "Cannot be parsed as the supported `<scheme>://<session_id>` form.",
        Keys.DIAG_STEP_USE_SUPPORTED_SCHEME: "Use a supported URI scheme.",
        Keys.DIAG_URI_SCANNED_NO_MATCH: "Scanned the currently available providers, but no session id matched.",
        Keys.DIAG_STEP_LIST_TO_CONFIRM: "Run `agent-dump --list` to confirm the session still exists.",
        Keys.DIAG_STEP_CHECK_URI_SESSION_ID: "Check that the session id in the URI is complete and belongs to that provider.",
        Keys.DIAG_URI_SCHEME_MISMATCH: "The URI scheme does not match the actual session source.",
        Keys.DIAG_URI_BELONGS_TO: "This session actually belongs to {agent}.",
        Keys.DIAG_STEP_USE_THIS_URI: "Re-run with `{uri}`.",
        Keys.DIAG_QUERY_URI_INVALID: "Invalid agents:// query.",
        Keys.DIAG_STEP_CHECK_QUERY_URI_SHAPE: "Check that the `agents://<path>?q=<keyword>&providers=<names>` structure is complete.",
        Keys.DIAG_STEP_NO_QUERY_URI_WITH_Q: "Do not combine `agents://...` with `-q/--query`.",
        Keys.DIAG_QUERY_COMBINATION_INVALID: "Invalid query argument combination.",
        Keys.DIAG_QUERY_URI_WITH_Q_DETAIL: "an agents:// query cannot be combined with -q/--query",
        Keys.DIAG_STEP_DROP_Q: "Remove `-q/--query`, or switch to plain list/interactive mode.",
        Keys.DIAG_PRINT_UNSUPPORTED_MODE: "The current mode does not support print export.",
        Keys.DIAG_PRINT_UNSUPPORTED_DETAIL: "--interactive does not support print; only json, markdown and raw",
        Keys.DIAG_STEP_DROP_PRINT: "Remove `print` and use `json`, `markdown` or `raw`.",
        Keys.DIAG_QUERY_SPEC_INVALID: "Invalid query expression.",
        Keys.DIAG_STEP_QUERY_FORMAT: "Use the `keyword` or `agent1,agent2:keyword` form.",
        Keys.DIAG_STEP_QUERY_URI_FOR_PATH: "For a path-scoped query use `agents://<path>?q=<keyword>&providers=<names>`.",
        Keys.DIAG_NO_PROVIDER_IN_SCOPE: "No usable provider within the query scope.",
        Keys.DIAG_STEP_CONFIRM_PROVIDERS_HAVE_DATA: "Confirm those providers actually have session data on this machine.",
        Keys.DIAG_STEP_WIDEN_PROVIDERS: "Widen the providers scope, or run `--list` without a provider filter first.",
        Keys.INDEX_UPDATE_PROGRESS: "Updating the {agent} search index ({count} sessions; the first run can be slow)…",
        Keys.WARN_INDEX_SKIPPED_SESSIONS: "⚠️  {agent}: {count} sessions could not be read and were not indexed; the next run retries them (e.g. {examples})",
        Keys.WARN_JSONL_RECORDS_SKIPPED: "⚠️  {path}: skipped {count} malformed records (lines {lines})",
        Keys.WARN_INDEX_UNUSABLE: "⚠️  The {agent} search index is unusable ({error_type}: {error}); falling back to a file scan. Run `agent-dump --reindex` to rebuild it.",
        Keys.WARN_SESSION_SUMMARY_SKIPPED: "⚠️  Session summary failed, skipped {uri}: {error}",
        Keys.WARN_SESSION_SUMMARY_FAILURES: "⚠️  {count} session summaries failed; the final report omits those sessions.",
        Keys.DIAG_STEP_RAW_SOURCE_LOCAL: "Confirm the original session file is still on this machine.",
        Keys.DIAG_STEP_LIST_TO_CHECK_VISIBLE: "Re-run `agent-dump --list` to check whether the session is still visible.",
        Keys.DIAG_STEP_USE_JSON_OR_MARKDOWN: "Use `--format json` or `--format markdown` instead.",
        Keys.DIAG_STEP_CHECK_PROVIDER_HAS_RAW: "If you need the original file, check whether this provider keeps a standalone raw file.",
        Keys.DIAG_STEP_CODEX_SESSION_LOCATION: "Confirm the Codex session file is still under `CODEX_HOME/sessions` or the local development data directory.",
        Keys.DIAG_STEP_LIST_TO_CHECK_ID: "Re-run `agent-dump --list` to confirm the session id still exists.",
        Keys.DIAG_STEP_CLAUDE_SESSION_LOCATION: "Confirm the Claude Code session file is still under the projects directory.",
        Keys.DIAG_STEP_LIST_TO_CHECK_EXISTS: "Re-run `agent-dump --list` to confirm the session still exists.",
        Keys.DIAG_STEP_KIMI_NEEDS_JSONL: "Confirm the session directory holds at least `context.jsonl` or `wire.jsonl`.",
        Keys.DIAG_STEP_READABLE_EXPORT_INSTEAD: "For a readable export, use `--format json` or `--format markdown`.",
        Keys.DIAG_STEP_KIMI_SOURCE_INTACT: "Confirm the original Kimi session file has not been moved or cleaned up.",
        Keys.DIAG_STEP_KIMI_CONTEXT_INTACT: "Confirm `context.jsonl` in the session directory has not been cleaned up.",
        Keys.DIAG_STEP_KIMI_WIRE_FALLBACK: "If only `wire.jsonl` exists, use the wire-compatible path or re-export this session.",
        Keys.DIAG_STEP_KIMI_WIRE_INTACT: "Confirm `wire.jsonl` in the session directory has not been cleaned up.",
        Keys.DIAG_STEP_KIMI_CONTEXT_FALLBACK: "If only `context.jsonl` exists, use the context export path.",
        Keys.DIAG_STEP_PI_SESSION_LOCATION: "Confirm the Pi session file is still under `PI_HOME/agent/sessions` or the local development data directory.",
        Keys.DIAG_STEP_CURSOR_DB_EXISTS: "Confirm `globalStorage/state.vscdb` still exists under the Cursor user directory.",
        Keys.DIAG_STEP_CURSOR_LIST_TO_CHECK: "Re-run `agent-dump --list --agent cursor` to check whether sessions are still visible.",
        Keys.DIAG_STEP_USE_JSON_OR_PRINT: "Use `--format json` or `--format print` instead.",
        Keys.DIAG_STEP_CURSOR_INSPECT_SQLITE: "To locate the data source, inspect the SQLite database under the Cursor user directory.",
        Keys.DIAG_STEP_OPENCODE_DB_EXISTS: "Confirm OpenCode has produced a session database on this machine.",
        Keys.DIAG_STEP_OPENCODE_DEV_DB: "In a test or development environment, check whether `data/opencode/opencode.db` exists.",
        Keys.DIAG_STEP_ZCODE_DB_EXISTS: "Confirm ZCode has produced a session database on this macOS or Windows machine.",
        Keys.DIAG_STEP_ZCODE_DB_PATHS: "On macOS check `~/.zcode/cli/db/db.sqlite`; on Windows check `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`.",
        Keys.DIAG_STEP_ZCODE_NO_LINUX: "Linux has no default ZCode session path.",
        Keys.QUERY_SUMMARY_PATH: "path={path}",
        Keys.QUERY_SUMMARY_KEYWORD: "keyword={keyword}",
        Keys.QUERY_SUMMARY_ALL_SESSIONS: "all sessions",
        Keys.QUERY_ERROR_EMPTY_SPEC: "query expression cannot be empty",
        Keys.QUERY_ERROR_UNKNOWN_AGENT: "unknown agent name: {name}",
        Keys.QUERY_ERROR_EMPTY_KEYWORD: "query keyword cannot be empty",
        Keys.QUERY_ERROR_EMPTY_PATH: "query path cannot be empty",
        Keys.QUERY_ERROR_EMPTY_PROVIDERS: "providers cannot be empty",
        Keys.QUERY_ERROR_EMPTY_ROLES: "roles cannot be empty",
        Keys.QUERY_ERROR_EMPTY_LIMIT: "limit cannot be empty",
        Keys.QUERY_ERROR_LIMIT_NOT_POSITIVE: "limit must be a positive integer",
        Keys.QUERY_ERROR_LIMIT_TOO_LARGE: "limit is too large",
        Keys.QUERY_ERROR_UNKNOWN_FIELD: "unknown query field: {field}",
        Keys.QUERY_ERROR_DUPLICATE_PATH: "path/cwd may only be given once",
        Keys.QUERY_ERROR_DUPLICATE_LIMIT: "limit may only be given once",
        Keys.PATCH_ERROR_EMPTY: "patch is empty",
        Keys.PATCH_ERROR_MISSING_HEADER: "patch is missing the Begin Patch header",
        Keys.PATCH_ERROR_MISSING_FOOTER: "patch is missing the End Patch footer",
        Keys.PATCH_ERROR_BAD_OPERATION: "cannot parse patch operation header: {line}",
        Keys.PATCH_ERROR_BAD_LINE: "cannot parse patch line: {line}",
        Keys.GROUP_HEADER_DISABLED_HINT: "group header",
        Keys.DIAGNOSTIC_PARSED_URI: "Parsed URI",
        Keys.DIAGNOSTIC_CAPABILITY_GAP: "Capability gap",
        Keys.DIAGNOSTIC_NEXT_STEPS: "Next steps",
        Keys.STATS_HEADER: "📊 Session Statistics (last {days} days)",
        Keys.STATS_TOTAL_SESSIONS: "Total sessions: {count}",
        Keys.STATS_TOTAL_MESSAGES: "Total messages: {count}",
        Keys.STATS_KNOWN_MESSAGES: "Known messages: {count} (unknown-count sessions: {unknown_sessions})",
        Keys.STATS_BY_AGENT: "By Agent",
        Keys.STATS_BY_TIME: "By Time",
        Keys.STATS_NO_SESSIONS: "No sessions found in the last {days} days.",
        Keys.STATS_AGENT_ROW: "  {name}: {sessions} sessions, {messages} messages",
        Keys.STATS_AGENT_ROW_WITH_UNKNOWN: (
            "  {name}: {sessions} sessions, {messages} known messages, unknown-count sessions: {unknown_sessions}"
        ),
        Keys.STATS_TIME_ROW: "  {label}: {count} sessions",
        Keys.MESSAGE_COUNT_UNKNOWN: "unknown",
        Keys.SESSION_COUNT_SUFFIX: "sessions",
    },
    "zh": {
        Keys.NO_AGENTS_FOUND: "❌ 未找到任何可用的 Agent Tools 会话。",
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
        Keys.SCANNING_AGENTS: "🔍 正在扫描 Agent Tools...\n",
        Keys.AGENT_FOUND: "   ✓ 发现 {name} ({count} 个会话)",
        Keys.AGENT_FOUND_EMPTY: "   ⚠ 发现 {name} (0 个会话)",
        Keys.TIME_TODAY: "今天",
        Keys.TIME_YESTERDAY: "昨天",
        Keys.TIME_THIS_WEEK: "本周",
        Keys.TIME_THIS_MONTH: "本月",
        Keys.TIME_OLDER: "更早",
        Keys.TIME_UNKNOWN: "未知时间",
        Keys.SELECT_AGENT_PROMPT: "选择要导出的 Agent Tool:",
        Keys.SELECT_INSTRUCTION: "\n↑↓ 移动  |  回车 选择  |  q 退出",
        Keys.USER_CANCELLED: "⚠️  用户取消操作，退出。",
        Keys.AVAILABLE_AGENTS: "可用的 Agent Tools:",
        Keys.SELECT_AGENT_NUMBER: "选择 Agent Tool 编号:",
        Keys.NO_INPUT_EXITING: "⚠️  未收到输入，已退出。",
        Keys.INVALID_SELECTION: "⚠️  选择无效: {selection}",
        Keys.INVALID_INPUT_NUMBER: "⚠️  输入无效，请输入一个数字。",
        Keys.NO_SESSIONS_IN_RANGE: "指定时间范围内没有会话。",
        Keys.GROUP_TITLE: "─── {group_name} ({count} 个) ───",
        Keys.SELECT_SESSIONS_PROMPT: "选择要导出的会话:",
        Keys.CHECKBOX_INSTRUCTION: "\n↑↓ 移动  |  空格 选择/取消  |  回车 确认  |  q 退出",
        Keys.AVAILABLE_SESSIONS: "可用会话:",
        Keys.ENTER_SESSION_NUMBERS: "输入要导出的会话编号（逗号分隔，如 '1,3,5'，或 'all'）:",
        Keys.INVALID_INPUT_NUMBERS: "⚠️  输入无效，请输入以逗号分隔的数字。",
        Keys.CLI_DESC: "导出 Agent 会话",
        Keys.CLI_URI_HELP: "要导出的 Agent 会话 URI，或使用 agents://<path>?q=<关键词>&providers=<名称>&roles=<名称>&limit=<数量> 做路径作用域查询",
        Keys.CLI_DAYS_HELP: "回溯最近几天的会话（默认 7；collect 未指定时仅当天）",
        Keys.CLI_OUTPUT_HELP: "JSON/raw 输出目录（默认: config export.output，其次 ./sessions）",
        Keys.CLI_FORMAT_HELP: "输出格式: json | markdown | raw | print（支持逗号分隔，兼容 md 别名）",
        Keys.CLI_HEAD_HELP: "仅查看 URI 会话的轻量元数据摘要，不导出文件也不打印正文",
        Keys.CLI_SUMMARY_HELP: "为 URI JSON 导出生成 AI 总结（需要配置且 format 包含 json）",
        Keys.CLI_LIST_HELP: "列出所有可用会话而不导出",
        Keys.CLI_QUERY_HELP: "查询过滤。兼容旧语法 'agent1,agent2:keyword' / 'keyword'，也支持结构化词项，如 'bug provider:codex role:user path:. limit:20'；不能与 agents:// 查询 URI 同时使用",
        Keys.CLI_INTERACTIVE_HELP: "进入交互式模式选择并导出",
        Keys.CLI_NO_METADATA_SUMMARY_HELP: "在列表和交互视图中隐藏高信号元数据摘要",
        Keys.CLI_SAVE_HELP: "collect 输出路径：可传目录或 .md 文件路径（支持绝对/相对路径）",
        Keys.CLI_PAGE_SIZE_HELP: "为兼容保留，当前不生效",
        Keys.CLI_LANG_HELP: "语言 (en, zh). 默认: 自动检测",
        Keys.CLI_COLLECT_HELP: "按日期收集会话 print 内容并调用 AI 生成总结",
        Keys.CLI_COLLECT_MODE_HELP: "收集输出模式: pm（项目管理）或 insight（作者洞察）",
        Keys.CLI_DRY_RUN_HELP: "预览 collect 工作量，跳过 AI 请求和文件写入",
        Keys.CLI_SHORTCUT_HELP: "执行已配置的 shortcut 预设",
        Keys.CLI_SINCE_HELP: "收集开始日期 (YYYY-MM-DD 或 YYYYMMDD)",
        Keys.CLI_UNTIL_HELP: "收集结束日期 (YYYY-MM-DD 或 YYYYMMDD)",
        Keys.CLI_CONFIG_HELP: "管理 AI 配置 (view|edit)",
        Keys.CLI_STATS_HELP: "显示会话使用统计",
        Keys.CLI_SEARCH_HELP: "全文搜索关键词（通过索引搜索消息内容）",
        Keys.CLI_REINDEX_HELP: "强制重建全文搜索索引",
        Keys.CLI_PROVIDERS_HELP: "显示 provider 能力矩阵与本地搜索路径",
        Keys.CLI_VERSION_HELP: "显示版本号并退出（-v, --version）",
        Keys.CLI_FORMAT_INVALID: "无效的格式列表: {value}",
        Keys.CLI_DAYS_INVALID: "无效的回溯天数: {value}；必须为日历范围内的正整数",
        Keys.SEARCH_INDEX_NOT_AVAILABLE: "⚠️  全文搜索不可用（SQLite 不支持 FTS5）。",
        Keys.SEARCH_HEADER: "🔎 搜索最近 {days} 天内匹配「{query}」的会话:\n",
        Keys.SEARCH_NO_RESULTS: "   (无搜索结果)",
        Keys.SEARCH_RESULT_PROVIDER: "来源",
        Keys.SEARCH_RESULT_UPDATED: "更新时间",
        Keys.SEARCH_RESULT_URI: "URI",
        Keys.SEARCH_RESULT_RANK: "匹配度",
        Keys.SEARCH_RESULT_SNIPPET: "命中片段",
        Keys.REINDEX_START: "🔄 正在重建搜索索引...",
        Keys.REINDEX_AGENT_DONE: "   ✓ {agent}: 已索引 {count} 个会话",
        Keys.REINDEX_DONE: "✅ 索引重建完成。共索引 {count} 个会话。",
        Keys.PROVIDERS_HEADER: "Provider 能力矩阵",
        Keys.PROVIDERS_TABLE_HEADER: "Provider | URI | 导出格式 | 存储级关键词快路径 | 搜索路径 | 不支持",
        Keys.PROVIDERS_ROW: "{provider} | {uri} | {formats} | {keyword} | {roots} | {unsupported}",
        Keys.PROVIDERS_YES: "是",
        Keys.PROVIDERS_NO: "否",
        Keys.PROVIDERS_NONE: "无",
        Keys.PROVIDERS_ROOT_COUNT: "已找到 {existing}/{total}",
        Keys.PROVIDERS_SEARCH_ROOTS: "搜索路径",
        Keys.PROVIDERS_ROOT_NONE: "  - [不可用] 当前平台无默认路径",
        Keys.PROVIDERS_ROOT_EXISTS: "已找到",
        Keys.PROVIDERS_ROOT_MISSING: "未找到",
        Keys.PROVIDERS_ROOT_ROW: "  - [{status}] {label}: {path}",
        Keys.LIST_IGNORE_FORMAT: "⚠️  --list 模式会忽略 -format/--format 参数。",
        Keys.LIST_IGNORE_OUTPUT: "⚠️  --list 模式会忽略 -output/--output 参数。",
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
        Keys.COLLECT_CONFIG_BAD_SCHEME: "❌ ai.base_url 必须使用 http 或 https。",
        Keys.COLLECT_CONFIG_PLAINTEXT_KEY: (
            "❌ ai.base_url 使用 http，api_key 会以明文发送。请改用 https，或把 base_url 指向本机 localhost。"
        ),
        Keys.COLLECT_CONFIG_HINT: "请先执行: agent-dump -config edit",
        Keys.COLLECT_READ_FAILED: "❌ collect 读取会话失败: {error}",
        Keys.COLLECT_NO_SESSIONS: "⚠️  在 {since} ~ {until} 区间内未找到会话。",
        Keys.COLLECT_API_FAILED: "❌ AI 总结请求失败: {error}",
        Keys.COLLECT_OUTPUT_SAVED: "✅ collect 总结已保存: {path}",
        Keys.COLLECT_DRY_RUN_HEADER: "Collect dry-run 预览",
        Keys.COLLECT_DRY_RUN_DATE_RANGE: "日期范围：{since} ~ {until}",
        Keys.COLLECT_DRY_RUN_PROVIDER_BREAKDOWN: "Provider 分布：{breakdown}",
        Keys.COLLECT_DRY_RUN_SESSION_COUNT: "Session 数：{count}",
        Keys.COLLECT_DRY_RUN_CHUNK_COUNT: "Chunk 数：{count}",
        Keys.COLLECT_DRY_RUN_CONCURRENCY: "并发配置：{concurrency}",
        Keys.COLLECT_DRY_RUN_SAVE_PATH: "保存路径：{path}",
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
        Keys.DIAGNOSTIC_SEARCHED_ROOTS: "已检查路径",
        Keys.WARN_SESSION_LOOKUP_FAILED: "警告: {agent} 查找会话失败: {error}",
        Keys.WARN_PROVIDER_OPERATION_FAILED: "警告: {agent} provider 操作失败: {error_type}: {error}",
        Keys.WARN_SESSION_PARSE_FAILED: "警告: 解析会话文件失败 {path}: {error}",
        Keys.WARN_TITLE_CACHE_FAILED: "警告: 加载标题缓存失败: {error}",
        Keys.WARN_TITLE_EXTRACT_FAILED: "警告: 提取标题失败: {error}",
        Keys.WARN_MESSAGE_CONVERT_FAILED: "警告: 转换消息格式失败: {error}",
        Keys.WARN_CONTEXT_CONVERT_FAILED: "警告: 转换 context 记录失败: {error}",
        Keys.WARN_WIRE_CONVERT_FAILED: "警告: 转换 wire 记录失败: {error}",
        Keys.WARN_PI_RECORD_CONVERT_FAILED: "警告: 转换 Pi 记录失败: {error}",
        Keys.WARN_MESSAGE_DATA_PARSE_FAILED: "警告: 解析消息数据失败 message={message_id}",
        Keys.WARN_PART_DATA_PARSE_FAILED: "警告: 解析消息分段数据失败 part={part_id}",
        Keys.WARN_INSECURE_BASE_URL: "警告: AI base_url 未使用 HTTPS，api_key 可能以明文传输。",
        Keys.DIAG_SESSION_NOT_FOUND: "未找到匹配的会话。",
        Keys.DIAG_UNEXPECTED_FAILURE: "命令因未预期的错误中止。",
        Keys.DIAG_STEP_RETRY_ONCE: "重试一次以确认是否为瞬时故障。",
        Keys.DIAG_STEP_FILE_ISSUE: "若可稳定复现，请带上上面的错误类型与命令参数提交 issue。",
        Keys.DIAG_STEP_PICK_ANOTHER_SESSION: "选择其他会话，或修复 provider 数据中的 session id。",
        Keys.DIAG_URI_CAPABILITY_GAP: "当前 URI 请求了 {agent} 不支持的导出能力。",
        Keys.DIAG_URI_CAPABILITY_DETAIL: "{agent} URI 仅支持 {supported}；当前请求了 {requested}",
        Keys.DIAG_STEP_DROP_FORMATS: "移除 {formats}，改用支持的格式。",
        Keys.DIAG_STEP_EXPORT_JSON_FIRST: "若需要进一步处理，先导出 JSON 再做转换。",
        Keys.DIAG_NO_LOCAL_SESSIONS: "未找到任何可用的本地会话数据。",
        Keys.DIAG_STEP_CHECK_AGENT_DATA: "确认对应 agent 已在本机生成过会话数据。",
        Keys.DIAG_STEP_CHECK_ENV_VARS: "若使用自定义目录，检查相关环境变量是否指向正确位置。",
        Keys.DIAG_STEP_CHECK_DEV_FALLBACK: "若在开发环境，检查 `data/<agent>` 回退目录是否存在。",
        Keys.DIAG_SESSION_READ_FAILED: "读取会话数据失败。",
        Keys.DIAG_STEP_CHECK_LOCAL_SOURCE: "检查本地会话源文件或数据库是否仍存在。",
        Keys.DIAG_STEP_NARROW_WITH_LIST: "若问题持续，先用 `agent-dump --list` 缩小范围再重试。",
        Keys.DIAG_URI_INVALID: "URI 格式无效。",
        Keys.DIAG_URI_UNPARSEABLE: "无法解析为受支持的 `<scheme>://<session_id>` 形式。",
        Keys.DIAG_STEP_USE_SUPPORTED_SCHEME: "改用受支持的 URI scheme。",
        Keys.DIAG_URI_SCANNED_NO_MATCH: "已扫描当前可用 provider，但未匹配到该 session id。",
        Keys.DIAG_STEP_LIST_TO_CONFIRM: "先运行 `agent-dump --list` 确认该会话是否仍存在。",
        Keys.DIAG_STEP_CHECK_URI_SESSION_ID: "检查 URI 中的 session id 是否完整且对应正确 provider。",
        Keys.DIAG_URI_SCHEME_MISMATCH: "URI scheme 与实际会话来源不匹配。",
        Keys.DIAG_URI_BELONGS_TO: "该会话实际属于 {agent}。",
        Keys.DIAG_STEP_USE_THIS_URI: "改用 `{uri}` 重新执行。",
        Keys.DIAG_QUERY_URI_INVALID: "agents:// 查询无效。",
        Keys.DIAG_STEP_CHECK_QUERY_URI_SHAPE: "检查 `agents://<path>?q=<keyword>&providers=<names>` 结构是否完整。",
        Keys.DIAG_STEP_NO_QUERY_URI_WITH_Q: "不要把 `agents://...` 与 `-q/--query` 同时使用。",
        Keys.DIAG_QUERY_COMBINATION_INVALID: "查询参数组合无效。",
        Keys.DIAG_QUERY_URI_WITH_Q_DETAIL: "agents:// 查询不能与 -q/--query 同时使用",
        Keys.DIAG_STEP_DROP_Q: "删除 `-q/--query`，或改用普通列表/交互模式。",
        Keys.DIAG_PRINT_UNSUPPORTED_MODE: "当前模式不支持 print 导出。",
        Keys.DIAG_PRINT_UNSUPPORTED_DETAIL: "--interactive 模式不支持 print；仅支持 json、markdown、raw",
        Keys.DIAG_STEP_DROP_PRINT: "移除 `print`，改用 `json`、`markdown` 或 `raw`。",
        Keys.DIAG_QUERY_SPEC_INVALID: "查询条件无效。",
        Keys.DIAG_STEP_QUERY_FORMAT: "使用 `关键词` 或 `agent1,agent2:关键词` 格式。",
        Keys.DIAG_STEP_QUERY_URI_FOR_PATH: "如需路径作用域查询，改用 `agents://<path>?q=<keyword>&providers=<names>`。",
        Keys.DIAG_NO_PROVIDER_IN_SCOPE: "查询范围内没有可用 provider。",
        Keys.DIAG_STEP_CONFIRM_PROVIDERS_HAVE_DATA: "确认这些 provider 在本机上确实存在会话数据。",
        Keys.DIAG_STEP_WIDEN_PROVIDERS: "放宽 providers 范围，或先不加 provider 过滤执行 `--list`。",
        Keys.INDEX_UPDATE_PROGRESS: "正在更新 {agent} 的搜索索引（{count} 个会话，首次运行可能较慢）…",
        Keys.WARN_INDEX_SKIPPED_SESSIONS: "警告: {agent} 有 {count} 个会话读取失败，未写入索引，下次运行会重试（示例: {examples}）",
        Keys.WARN_JSONL_RECORDS_SKIPPED: "警告: {path} 跳过了 {count} 条格式错误的记录（行 {lines}）",
        Keys.WARN_INDEX_UNUSABLE: "警告: {agent} 的搜索索引不可用（{error_type}: {error}），本次改用文件扫描；可运行 `agent-dump --reindex` 重建索引。",
        Keys.WARN_SESSION_SUMMARY_SKIPPED: "警告: 会话摘要失败，已跳过 {uri}: {error}",
        Keys.WARN_SESSION_SUMMARY_FAILURES: "警告: {count} 个会话摘要失败，最终报告不包含这些会话。",
        Keys.DIAG_STEP_RAW_SOURCE_LOCAL: "确认原始会话文件仍在本地。",
        Keys.DIAG_STEP_LIST_TO_CHECK_VISIBLE: "重新运行 `agent-dump --list` 检查该会话是否仍可见。",
        Keys.DIAG_STEP_USE_JSON_OR_MARKDOWN: "改用 `--format json` 或 `--format markdown`。",
        Keys.DIAG_STEP_CHECK_PROVIDER_HAS_RAW: "若需要原始文件，请检查该 provider 是否有独立 raw 文件。",
        Keys.DIAG_STEP_CODEX_SESSION_LOCATION: "确认 Codex 会话文件仍在 `CODEX_HOME/sessions` 或本地开发数据目录。",
        Keys.DIAG_STEP_LIST_TO_CHECK_ID: "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。",
        Keys.DIAG_STEP_CLAUDE_SESSION_LOCATION: "确认 Claude Code 会话文件仍位于 projects 目录下。",
        Keys.DIAG_STEP_LIST_TO_CHECK_EXISTS: "重新运行 `agent-dump --list` 确认该会话是否仍存在。",
        Keys.DIAG_STEP_KIMI_NEEDS_JSONL: "确认该会话目录下至少存在 `context.jsonl` 或 `wire.jsonl`。",
        Keys.DIAG_STEP_READABLE_EXPORT_INSTEAD: "若只需要可读导出，改用 `--format json` 或 `--format markdown`。",
        Keys.DIAG_STEP_KIMI_SOURCE_INTACT: "确认原始 Kimi 会话文件没有被移动或清理。",
        Keys.DIAG_STEP_KIMI_CONTEXT_INTACT: "确认会话目录中的 `context.jsonl` 未被清理。",
        Keys.DIAG_STEP_KIMI_WIRE_FALLBACK: "如果只有 `wire.jsonl`，请改走 wire 兼容路径或重新导出该会话。",
        Keys.DIAG_STEP_KIMI_WIRE_INTACT: "确认会话目录中的 `wire.jsonl` 未被清理。",
        Keys.DIAG_STEP_KIMI_CONTEXT_FALLBACK: "如果只有 `context.jsonl`，请改走 context 导出路径。",
        Keys.DIAG_STEP_PI_SESSION_LOCATION: "确认 Pi 会话文件仍在 `PI_HOME/agent/sessions` 或本地开发数据目录。",
        Keys.DIAG_STEP_CURSOR_DB_EXISTS: "确认 Cursor 用户目录下的 globalStorage/state.vscdb 仍存在。",
        Keys.DIAG_STEP_CURSOR_LIST_TO_CHECK: "重新运行 `agent-dump --list --agent cursor` 检查会话是否仍可见。",
        Keys.DIAG_STEP_USE_JSON_OR_PRINT: "改用 `--format json` 或 `--format print`。",
        Keys.DIAG_STEP_CURSOR_INSPECT_SQLITE: "若需要定位数据源，请检查 Cursor 用户目录下的 SQLite 数据库。",
        Keys.DIAG_STEP_OPENCODE_DB_EXISTS: "确认 OpenCode 已在本机生成会话数据库。",
        Keys.DIAG_STEP_OPENCODE_DEV_DB: "若在测试或开发环境，检查 `data/opencode/opencode.db` 是否存在。",
        Keys.DIAG_STEP_ZCODE_DB_EXISTS: "确认 ZCode 已在 macOS 或 Windows 本机生成会话数据库。",
        Keys.DIAG_STEP_ZCODE_DB_PATHS: "macOS 检查 `~/.zcode/cli/db/db.sqlite`；Windows 检查 `%USERPROFILE%\\.zcode\\cli\\db\\db.sqlite`。",
        Keys.DIAG_STEP_ZCODE_NO_LINUX: "Linux 暂无 ZCode 默认会话路径。",
        Keys.QUERY_SUMMARY_PATH: "路径={path}",
        Keys.QUERY_SUMMARY_KEYWORD: "关键词={keyword}",
        Keys.QUERY_SUMMARY_ALL_SESSIONS: "全部会话",
        Keys.QUERY_ERROR_EMPTY_SPEC: "查询条件不能为空",
        Keys.QUERY_ERROR_UNKNOWN_AGENT: "未知 agent 名称: {name}",
        Keys.QUERY_ERROR_EMPTY_KEYWORD: "查询关键词不能为空",
        Keys.QUERY_ERROR_EMPTY_PATH: "查询路径不能为空",
        Keys.QUERY_ERROR_EMPTY_PROVIDERS: "providers 不能为空",
        Keys.QUERY_ERROR_EMPTY_ROLES: "roles 不能为空",
        Keys.QUERY_ERROR_EMPTY_LIMIT: "limit 不能为空",
        Keys.QUERY_ERROR_LIMIT_NOT_POSITIVE: "limit 必须是正整数",
        Keys.QUERY_ERROR_LIMIT_TOO_LARGE: "limit 数值过大",
        Keys.QUERY_ERROR_UNKNOWN_FIELD: "未知查询字段: {field}",
        Keys.QUERY_ERROR_DUPLICATE_PATH: "path/cwd 只能指定一次",
        Keys.QUERY_ERROR_DUPLICATE_LIMIT: "limit 只能指定一次",
        Keys.PATCH_ERROR_EMPTY: "patch 为空",
        Keys.PATCH_ERROR_MISSING_HEADER: "patch 缺少 Begin Patch 头",
        Keys.PATCH_ERROR_MISSING_FOOTER: "patch 缺少 End Patch 尾",
        Keys.PATCH_ERROR_BAD_OPERATION: "无法解析 patch 操作头: {line}",
        Keys.PATCH_ERROR_BAD_LINE: "无法解析 patch 行: {line}",
        Keys.GROUP_HEADER_DISABLED_HINT: "分组标题",
        Keys.DIAGNOSTIC_PARSED_URI: "解析后的 URI",
        Keys.DIAGNOSTIC_CAPABILITY_GAP: "缺失能力",
        Keys.DIAGNOSTIC_NEXT_STEPS: "下一步",
        Keys.STATS_HEADER: "📊 会话统计 (最近 {days} 天)",
        Keys.STATS_TOTAL_SESSIONS: "总会话数: {count}",
        Keys.STATS_TOTAL_MESSAGES: "总消息数: {count}",
        Keys.STATS_KNOWN_MESSAGES: "已知消息数: {count}（{unknown_sessions} 个会话的消息数未知）",
        Keys.STATS_BY_AGENT: "按 Agent",
        Keys.STATS_BY_TIME: "按时间",
        Keys.STATS_NO_SESSIONS: "最近 {days} 天内未找到会话。",
        Keys.STATS_AGENT_ROW: "  {name}: {sessions} 个会话, {messages} 条消息",
        Keys.STATS_AGENT_ROW_WITH_UNKNOWN: (
            "  {name}: {sessions} 个会话, {messages} 条已知消息, {unknown_sessions} 个会话的消息数未知"
        ),
        Keys.STATS_TIME_ROW: "  {label}: {count} 个会话",
        Keys.MESSAGE_COUNT_UNKNOWN: "未知",
        Keys.SESSION_COUNT_SUFFIX: "个会话",
    },
}


# 测试期置 True（见 tests/conftest.py），让 t() 的占位符不匹配直接抛错
STRICT_FORMATTING = False


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
                # 生产环境宁可漏出模板也不要因文案问题崩掉命令；测试期开启严格模式，
                # 让占位符不匹配在 CI 失败，而不是把字面 {days} 交给用户
                if STRICT_FORMATTING:
                    raise
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
