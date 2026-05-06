import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from agent_dump.agent_registry import (
    get_supported_agent_locations as _get_supported_agent_locations,
    get_uri_scheme_map,
)
from agent_dump.agents.base import BaseAgent, Session
from agent_dump.diagnostics import (
    DiagnosticError,
    invalid_query_or_uri,
    render_diagnostic,
    root_not_found,
    unsupported_capability,
)
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot
from agent_dump.query_filter import (
    QuerySpec,
    SearchSessionMatch,
    filter_sessions,
    filter_sessions_by_query,
    limit_query_matches,
    limit_search_matches,
    search_sessions_by_query,
)
from agent_dump.rendering import (
    apply_summary_to_json_export as _apply_summary_to_json_export,
    export_session_in_format as _export_session_in_format,
    export_session_markdown as _export_session_markdown,
    format_session_metadata_summary as _format_session_metadata_summary,
    render_session_head as _render_session_head,
    render_session_text as _render_session_text,
)
from agent_dump.scanner import AgentScanner
from agent_dump.time_utils import get_local_timezone, to_local_datetime
from agent_dump.uri_support import find_session_by_id as _find_session_by_id, parse_uri as _parse_uri

VALID_URI_SCHEMES = get_uri_scheme_map()
VALID_FORMATS = {"json", "markdown", "raw", "print"}
FORMAT_ALIASES = {"md": "markdown"}
DEFAULT_OUTPUT_BASE_DIR = Path("./sessions")


def parse_uri(uri: str) -> tuple[str, str] | None:
    return _parse_uri(uri)


def find_session_by_id(scanner: AgentScanner, session_id: str) -> tuple[BaseAgent, Session] | None:
    return _find_session_by_id(scanner, session_id)


def render_session_text(uri: str, session_data: dict[str, Any]) -> str:
    return _render_session_text(uri, session_data)


def format_session_metadata_summary(agent: BaseAgent, session: Session) -> str:
    return _format_session_metadata_summary(agent, session)


def render_session_head(uri: str, session_head: dict[str, Any]) -> str:
    return _render_session_head(uri, session_head)


def apply_summary_to_json_export(output_path: Path, summary_markdown: str) -> None:
    _apply_summary_to_json_export(output_path, summary_markdown)


def format_relative_time(time_value: datetime | float) -> str:
    if isinstance(time_value, (int, float)):
        time_value = datetime.fromtimestamp(time_value)

    now = datetime.now()
    delta = now - time_value

    if delta.days == 0:
        if delta.seconds < 3600:
            minutes = delta.seconds // 60
            return i18n.t(Keys.TIME_MINUTES_AGO, minutes=minutes) if minutes > 0 else i18n.t(Keys.TIME_JUST_NOW)
        hours = delta.seconds // 3600
        return i18n.t(Keys.TIME_HOURS_AGO, hours=hours)
    if delta.days == 1:
        return i18n.t(Keys.TIME_YESTERDAY)
    if delta.days < 7:
        return i18n.t(Keys.TIME_DAYS_AGO, days=delta.days)
    if delta.days < 30:
        weeks = delta.days // 7
        return i18n.t(Keys.TIME_WEEKS_AGO, weeks=weeks)
    return time_value.strftime("%Y-%m-%d")


def group_sessions_by_time(sessions: list[Session]) -> dict[str, list[Session]]:
    groups: dict[str, list[Session]] = {
        i18n.t(Keys.TIME_TODAY): [],
        i18n.t(Keys.TIME_YESTERDAY): [],
        i18n.t(Keys.TIME_THIS_WEEK): [],
        i18n.t(Keys.TIME_THIS_MONTH): [],
        i18n.t(Keys.TIME_OLDER): [],
    }

    key_today = i18n.t(Keys.TIME_TODAY)
    key_yesterday = i18n.t(Keys.TIME_YESTERDAY)
    key_week = i18n.t(Keys.TIME_THIS_WEEK)
    key_month = i18n.t(Keys.TIME_THIS_MONTH)
    key_older = i18n.t(Keys.TIME_OLDER)

    local_tz = get_local_timezone()
    now = datetime.now(local_tz)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    for session in sessions:
        session_time = to_local_datetime(session.created_at, local_tz)

        if session_time >= today:
            groups[key_today].append(session)
        elif session_time >= yesterday:
            groups[key_yesterday].append(session)
        elif session_time >= week_ago:
            groups[key_week].append(session)
        elif session_time >= month_ago:
            groups[key_month].append(session)
        else:
            groups[key_older].append(session)

    return {k: v for k, v in groups.items() if v}


def display_sessions_list(
    agent: BaseAgent,
    sessions: list[Session],
    page_size: int = 20,
    show_pagination: bool = True,
    show_metadata_summary: bool = True,
) -> bool:
    total = len(sessions)

    if total == 0:
        print(i18n.t(Keys.NO_SESSIONS_PAREN))
        return False

    current_page = 0
    total_pages = (total + page_size - 1) // page_size

    while True:
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total)

        for i in range(start_idx, end_idx):
            session = sessions[i]
            title = agent.get_formatted_title(session)
            if show_metadata_summary:
                summary = format_session_metadata_summary(agent, session)
                print(f"   • {title}")
                print(f"     {summary}")
            else:
                uri = agent.get_session_uri(session)
                print(f"   • {title} {uri}")

        if show_pagination and total_pages > 1:
            print(
                "\n   "
                + i18n.t(Keys.PAGINATION_INFO, current=current_page + 1, total=total_pages, total_sessions=total)
            )

            if current_page < total_pages - 1:
                print("   " + i18n.t(Keys.PAGINATION_PROMPT))
                try:
                    user_input = input("> ").strip().lower()
                    if user_input == "q":
                        return True
                    current_page += 1
                    print()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return True
            else:
                print("   " + i18n.t(Keys.PAGINATION_DONE))
                break
        else:
            if total > page_size:
                print("\n   " + i18n.t(Keys.PAGINATION_REMAINING, count=total - page_size))
            break

    return False


def export_sessions(agent: BaseAgent, sessions: list[Session], output_base_dir: Path) -> list[Path]:
    return export_sessions_for_formats(agent, sessions, ["json"], output_base_dir)


def export_session_markdown(uri: str, session_data: dict, session_id: str, output_dir: Path) -> Path:
    return _export_session_markdown(uri, session_data, session_id, output_dir)


def export_session_in_format(
    agent: BaseAgent,
    session: Session,
    output_dir: Path,
    output_format: str,
    *,
    session_data: dict[str, Any] | None = None,
    session_uri: str | None = None,
) -> Path:
    return _export_session_in_format(
        agent,
        session,
        output_dir,
        output_format,
        session_data=session_data,
        session_uri=session_uri,
    )


def export_sessions_for_formats(
    agent: BaseAgent,
    sessions: list[Session],
    formats: list[str],
    output_base_dir: Path,
    *,
    output_base_dirs: dict[str, Path] | None = None,
) -> list[Path]:
    print(i18n.t(Keys.EXPORTING_AGENT, agent_name=agent.display_name))
    exported: list[Path] = []
    for session in sessions:
        session_data: dict[str, Any] | None = None
        session_uri: str | None = None
        for output_format in formats:
            try:
                format_base_dir = (
                    output_base_dirs.get(output_format, output_base_dir)
                    if output_base_dirs is not None
                    else output_base_dir
                )
                output_dir = format_base_dir / agent.name
                output_dir.mkdir(parents=True, exist_ok=True)
                if output_format == "markdown":
                    session_data = session_data if session_data is not None else agent.get_session_data(session)
                    session_uri = session_uri if session_uri is not None else agent.get_session_uri(session)

                output_path = export_session_in_format(
                    agent,
                    session,
                    output_dir,
                    output_format,
                    session_data=session_data,
                    session_uri=session_uri,
                )
                exported.append(output_path)
                print(
                    i18n.t(
                        Keys.EXPORT_SUCCESS_FORMAT,
                        title=session.title[:50],
                        format=output_format,
                        filename=output_path.name,
                    )
                )
            except Exception as e:
                print(i18n.t(Keys.EXPORT_ERROR_FORMAT, title=session.title[:50], format=output_format, error=str(e)))
                diagnostic = e if isinstance(e, DiagnosticError) else _wrap_runtime_fetch_error(e, agent=agent)
                print(render_diagnostic(diagnostic, t=i18n.t))

    return exported


def export_sessions_markdown(agent: BaseAgent, sessions: list[Session], output_base_dir: Path) -> list[Path]:
    return export_sessions_for_formats(agent, sessions, ["markdown"], output_base_dir)


def is_option_specified(argv: list[str], short_option: str, long_option: str) -> bool:
    return any(arg in (short_option, long_option) or arg.startswith(f"{long_option}=") for arg in argv)


def resolve_output_base_dir(
    *,
    cli_output: str | None,
    output_specified: bool,
    export_output: str,
    output_format: str,
) -> Path:
    if output_specified and cli_output:
        return Path(cli_output)
    if output_format in {"json", "raw"} and export_output:
        return Path(export_output)
    return DEFAULT_OUTPUT_BASE_DIR


def parse_format_spec(raw: str) -> list[str]:
    formats: list[str] = []
    seen: set[str] = set()

    for part in raw.split(","):
        normalized = FORMAT_ALIASES.get(part.strip().lower(), part.strip().lower())
        if not normalized:
            raise ValueError("empty format")
        if normalized not in VALID_FORMATS:
            raise ValueError(normalized)
        if normalized in seen:
            continue
        seen.add(normalized)
        formats.append(normalized)

    if not formats:
        raise ValueError("empty format")

    return formats


def resolve_effective_formats(args: argparse.Namespace, is_uri_mode: bool, format_specified: bool) -> list[str]:
    if format_specified and args.format:
        return parse_format_spec(args.format)
    return ["print"] if is_uri_mode else ["json"]


def render_query_summary(spec: QuerySpec) -> str:
    if (
        spec.project_path is None
        and spec.agent_names is None
        and spec.roles is None
        and spec.limit is None
        and spec.keyword
    ):
        return spec.keyword

    parts: list[str] = []
    if spec.project_path is not None:
        parts.append(f"路径={spec.project_path}")
    if spec.keyword:
        parts.append(f"关键词={spec.keyword}")
    if spec.agent_names:
        providers = ",".join(sorted(spec.agent_names))
        parts.append(f"providers={providers}")
    if spec.roles:
        roles = ",".join(sorted(spec.roles))
        parts.append(f"roles={roles}")
    if spec.limit is not None:
        parts.append(f"limit={spec.limit}")
    return "；".join(parts) if parts else "全部会话"


def apply_query_filter(agent: BaseAgent, sessions: list[Session], spec: QuerySpec | None) -> list[Session]:
    if spec is None:
        return sessions
    if spec.project_path is None and spec.roles is None and spec.limit is None and spec.keyword is not None:
        if spec.agent_names is not None and agent.name not in spec.agent_names:
            return []
        return filter_sessions(agent, sessions, spec.keyword)
    return filter_sessions_by_query(agent, sessions, spec)


def collect_query_matches(
    agents: list[BaseAgent],
    *,
    days: int,
    spec: QuerySpec,
) -> dict[str, list[Session]]:
    matched_pairs: list[tuple[BaseAgent, Session]] = []
    for agent in agents:
        sessions = agent.get_sessions(days=days)
        matched_sessions = apply_query_filter(agent, sessions, spec)
        matched_pairs.extend((agent, session) for session in matched_sessions)

    limited_pairs = limit_query_matches(matched_pairs, spec.limit)
    grouped: dict[str, list[Session]] = {}
    for agent, session in limited_pairs:
        grouped.setdefault(agent.name, []).append(session)
    return grouped


def collect_search_matches(
    agents: list[BaseAgent],
    *,
    days: int,
    spec: QuerySpec,
) -> list[SearchSessionMatch]:
    matches: list[SearchSessionMatch] = []
    for agent in agents:
        sessions = agent.get_sessions(days=days)
        matches.extend(search_sessions_by_query(agent, sessions, spec))
    return limit_search_matches(matches, spec.limit)


def display_search_results(matches: list[SearchSessionMatch]) -> None:
    if not matches:
        print(i18n.t(Keys.SEARCH_NO_RESULTS))
        return

    for index, match in enumerate(matches, start=1):
        title = match.agent.get_formatted_title(match.session)
        uri = match.agent.get_session_uri(match.session)
        updated = to_local_datetime(match.session.updated_at).strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"\n{index}. {title}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_PROVIDER)}: {match.agent.display_name}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_UPDATED)}: {updated}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_URI)}: {uri}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_RANK)}: {match.rank:.6g}")
        print(f"   {i18n.t(Keys.SEARCH_RESULT_SNIPPET)}: {match.snippet}")


def validate_formats_for_mode(formats: list[str], is_uri_mode: bool, is_list_mode: bool) -> None:
    if is_list_mode or is_uri_mode:
        return
    if "print" in formats:
        raise ValueError("interactive-print")


def validate_uri_agent_formats(agent: BaseAgent, formats: list[str]) -> None:
    if agent.name != "cursor":
        return
    unsupported = [fmt for fmt in formats if fmt in {"raw", "markdown"}]
    if unsupported:
        requested = ",".join(unsupported)
        raise unsupported_capability(
            "当前 URI 请求了 Cursor 不支持的导出能力。",
            capability_gap=f"Cursor URI 仅支持 json 与 print；当前请求了 {requested}",
            next_steps=(
                "移除 `raw` 或 `markdown`，改用 `json` 或 `print`。",
                "若需要进一步处理，先导出 JSON 再做转换。",
            ),
        )


def warn_list_ignored_options(output_specified: bool, format_specified: bool) -> None:
    if format_specified:
        print(i18n.t(Keys.LIST_IGNORE_FORMAT))
    if output_specified:
        print(i18n.t(Keys.LIST_IGNORE_OUTPUT))


def get_supported_agent_locations() -> list[str]:
    return _get_supported_agent_locations()


def render_agent_search_roots(agents: list[BaseAgent] | list[Any]) -> tuple[str, ...]:
    roots: list[str] = []
    for agent in agents:
        get_search_roots = getattr(agent, "get_search_roots", None)
        display_name = getattr(agent, "display_name", getattr(agent, "name", "agent"))
        if not callable(get_search_roots):
            continue
        provider_roots = [root.render() for root in cast(tuple[SearchRoot, ...], get_search_roots())]
        if not provider_roots:
            continue
        roots.extend(f"{display_name}: {entry}" for entry in provider_roots)
    return tuple(roots)


def print_diagnostic(error: DiagnosticError) -> None:
    print(render_diagnostic(error, t=i18n.t))


def build_no_agents_found_diagnostic(scanner: AgentScanner) -> DiagnosticError:
    agents = getattr(scanner, "agents", [])
    searched_roots = render_agent_search_roots(agents)
    if not searched_roots:
        searched_roots = tuple(location.strip() for location in get_supported_agent_locations())
    return root_not_found(
        "未找到任何可用的本地会话数据。",
        searched_roots=searched_roots,
        next_steps=(
            "确认对应 agent 已在本机生成过会话数据。",
            "若使用自定义目录，检查相关环境变量是否指向正确位置。",
            "若在开发环境，检查 `data/<agent>` 回退目录是否存在。",
        ),
    )


def wrap_runtime_fetch_error(exc: Exception, *, agent: BaseAgent | None = None) -> DiagnosticError:
    searched_roots = render_agent_search_roots([agent]) if agent is not None else ()
    return (
        invalid_query_or_uri(
            "读取会话数据失败。",
            details=(str(exc),),
            next_steps=(
                "检查本地会话源文件或数据库是否仍存在。",
                "若问题持续，先用 `agent-dump --list` 缩小范围再重试。",
            ),
        )
        if not searched_roots
        else root_not_found(
            "读取会话数据失败。",
            details=(str(exc),),
            searched_roots=searched_roots,
            next_steps=(
                "检查本地会话源文件或数据库是否仍存在。",
                "若问题持续，先用 `agent-dump --list` 缩小范围再重试。",
            ),
        )
    )


_render_agent_search_roots = render_agent_search_roots
_print_diagnostic = print_diagnostic
_build_no_agents_found_diagnostic = build_no_agents_found_diagnostic
_wrap_runtime_fetch_error = wrap_runtime_fetch_error
