"""
Query parsing and session filtering helpers.
"""

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent_dump.agents.base import BaseAgent, Session, derive_session_facts
from agent_dump.i18n import Keys, i18n
from agent_dump.query_semantics import TextQuery, TextQueryMode
from agent_dump.search_index import SearchIndex, extract_session_searchable_text_once
from agent_dump.terminal_output import render_terminal_message
from agent_dump.time_utils import normalize_datetime_utc
from agent_dump.transcript import read_message

AGENT_ALIASES = {
    "claude": "claudecode",
}
STRUCTURED_QUERY_KEYS = {"provider", "role", "path", "cwd", "limit"}
QUERY_PATH_KEYS = {"path", "cwd"}
_MAX_QUERY_LIMIT = (1 << 63) - 1


@dataclass(frozen=True)
class QuerySpec:
    """Parsed query option."""

    agent_names: set[str] | None
    keyword: str | None
    project_path: Path | None
    roles: set[str] | None
    limit: int | None


@dataclass(frozen=True)
class QuerySessionMatch:
    """A session selected by a query together with its matching evidence."""

    agent: BaseAgent
    session: Session
    snippet: str
    rank: float
    matched_role: str | None = None


SearchSessionMatch = QuerySessionMatch


def parse_query(raw: str | None, valid_agents: set[str]) -> QuerySpec | None:
    """
    Parse --query string.

    Supported formats:
    - "keyword"
    - "agent1,agent2:keyword"
    """
    if raw is None:
        return None

    query = raw.strip()
    if not query:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_SPEC))

    if _contains_structured_query_terms(query):
        return _parse_structured_query(raw=query, valid_agents=valid_agents)

    if ":" in query:
        scope_part, keyword_part = query.split(":", 1)
        scope = scope_part.strip()
        keyword = keyword_part.strip()
        scope_names = [name.strip().lower() for name in scope.split(",") if name.strip()]

        # Ambiguity rule:
        # - If scope includes multiple names, or one known/alias name,
        #   treat as agent scope syntax.
        # - Otherwise keep full string as a plain keyword query.
        has_known_scope = any(_normalize_agent_name(name, valid_agents) for name in scope_names)
        if scope_names and (len(scope_names) > 1 or has_known_scope):
            normalized_agents: set[str] = set()
            unknown_agents: list[str] = []
            for name in scope_names:
                normalized = _normalize_agent_name(name, valid_agents)
                if normalized is None:
                    unknown_agents.append(name)
                else:
                    normalized_agents.add(normalized)

            if unknown_agents:
                unknown = ",".join(sorted(set(unknown_agents)))
                raise ValueError(i18n.t(Keys.QUERY_ERROR_UNKNOWN_AGENT, name=unknown))

            if not keyword:
                raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_KEYWORD))

            return QuerySpec(
                agent_names=normalized_agents,
                keyword=keyword,
                project_path=None,
                roles=None,
                limit=None,
            )

    return QuerySpec(agent_names=None, keyword=query, project_path=None, roles=None, limit=None)


def parse_query_uri(raw_uri: str | None, valid_agents: set[str], cwd: Path | None = None) -> QuerySpec | None:
    """Parse structured agents query URI."""
    if raw_uri is None:
        return None

    parsed = urlparse(raw_uri)
    if parsed.scheme != "agents":
        return None

    project_path = _parse_query_uri_project_path(parsed, cwd=cwd)
    params = parse_qs(parsed.query, keep_blank_values=True)
    keyword = _extract_single_query_param(params, "q")
    providers = _extract_single_query_param(params, "providers")
    roles = _extract_single_query_param(params, "roles")
    limit = _extract_single_query_param(params, "limit")

    if keyword is not None:
        keyword = keyword.strip()
        if not keyword:
            keyword = None

    agent_names = _parse_provider_scope(providers, valid_agents) if providers is not None else None
    normalized_roles = _parse_roles(roles) if roles is not None else None
    normalized_limit = _parse_limit(limit) if limit is not None else None
    return QuerySpec(
        agent_names=agent_names,
        keyword=keyword,
        project_path=project_path,
        roles=normalized_roles,
        limit=normalized_limit,
    )


def filter_sessions(agent: BaseAgent, sessions: list[Session], keyword: str | None) -> list[Session]:
    """Filter sessions by keyword for one agent."""
    query = TextQuery.parse(keyword or "", TextQueryMode.KEYWORD)
    if query.is_empty:
        return sessions
    if not sessions:
        return []

    indexed = _try_indexed_search(agent, sessions, query)
    if indexed is not None:
        return indexed

    provider_matched = agent.filter_sessions_by_keyword(sessions, query.literals[0])
    if provider_matched is not None:
        return provider_matched

    return _filter_sessions_from_source_or_data(agent, sessions, query)


def search_sessions_by_query(agent: BaseAgent, sessions: list[Session], spec: QuerySpec) -> list[SearchSessionMatch]:
    """Search sessions while preserving snippets and rank."""
    if not (spec.keyword or "").strip():
        return []
    return _session_matches(agent, sessions, spec, mode=TextQueryMode.SEARCH_TERMS)


def query_session_matches(agent: BaseAgent, sessions: list[Session], spec: QuerySpec) -> list[SearchSessionMatch]:
    """Apply a query while preserving the evidence used to select each session."""
    return _session_matches(agent, sessions, spec, mode=TextQueryMode.KEYWORD)


def _session_matches(
    agent: BaseAgent,
    sessions: list[Session],
    spec: QuerySpec,
    *,
    mode: TextQueryMode,
) -> list[SearchSessionMatch]:
    if spec.agent_names is not None and agent.name not in spec.agent_names:
        return []

    keyword = (spec.keyword or "").strip()
    text_query = TextQuery.parse(keyword, mode)
    scoped_sessions = sessions
    if spec.project_path is not None:
        scoped_sessions = [
            session
            for session in scoped_sessions
            if (
                (session_path := extract_session_working_directory(session)) is not None
                and is_path_scope_match(spec.project_path, session_path)
            )
        ]

    if spec.roles is not None:
        return _role_search_matches(
            agent,
            scoped_sessions,
            spec.roles,
            None if text_query.is_empty else text_query,
            limit=spec.limit,
        )

    if text_query.is_empty:
        return [
            SearchSessionMatch(agent=agent, session=session, snippet=session.title, rank=0.0)
            for session in scoped_sessions
        ]

    # 只有在没有任何后置过滤时下推 limit：project scope 会在拿到结果之后再筛，
    # 先裁剪就会把本该入选的会话挡在 top-L 之外。每个 Provider 取 top-L 后做全局
    # L 路合并是正确的——全局前 L 里不可能出现某个 Provider 的第 L+1 条。
    pushdown_limit = spec.limit if spec.project_path is None else None
    indexed = _try_indexed_search_matches(agent, sessions, scoped_sessions, text_query, pushdown_limit)
    if indexed is not None:
        return indexed

    return _fallback_search_matches(agent, scoped_sessions, text_query)


def limit_search_matches(matches: list[SearchSessionMatch], limit: int | None) -> list[SearchSessionMatch]:
    """Apply stable ranking and one global search limit."""
    sorted_matches = sorted(matches, key=_search_match_sort_key)
    if limit is None or limit >= len(sorted_matches):
        return sorted_matches
    return sorted_matches[:limit]


def limit_query_session_matches(
    matches: list[SearchSessionMatch],
    limit: int | None,
) -> list[SearchSessionMatch]:
    """Apply list/collect recency ordering and one global limit to query evidence."""
    if limit is None:
        return matches
    return sorted(matches, key=_query_evidence_sort_key)[:limit]


def _normalize_agent_name(name: str, valid_agents: set[str]) -> str | None:
    normalized = AGENT_ALIASES.get(name, name)
    if normalized in valid_agents:
        return normalized
    return None


def _parse_query_uri_project_path(parsed_uri, cwd: Path | None) -> Path:
    raw_path = f"{parsed_uri.netloc}{parsed_uri.path}".strip()
    if not raw_path:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_PATH))
    return normalize_project_path(raw_path, cwd=cwd)


def _extract_single_query_param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _parse_provider_scope(raw: str, valid_agents: set[str]) -> set[str]:
    provider_names = [name.strip().lower() for name in raw.split(",") if name.strip()]
    if not provider_names:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_PROVIDERS))

    normalized_agents: set[str] = set()
    unknown_agents: list[str] = []
    for name in provider_names:
        normalized = _normalize_agent_name(name, valid_agents)
        if normalized is None:
            unknown_agents.append(name)
        else:
            normalized_agents.add(normalized)

    if unknown_agents:
        unknown = ",".join(sorted(set(unknown_agents)))
        raise ValueError(i18n.t(Keys.QUERY_ERROR_UNKNOWN_AGENT, name=unknown))

    return normalized_agents


def _parse_roles(raw: str) -> set[str]:
    role_names = {name.strip().lower() for name in raw.split(",") if name.strip()}
    if not role_names:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_ROLES))
    return role_names


def _parse_limit(raw: str) -> int:
    normalized = raw.strip()
    if not normalized:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_LIMIT))
    try:
        value = int(normalized)
    except ValueError as exc:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_LIMIT_NOT_POSITIVE)) from exc
    if value <= 0:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_LIMIT_NOT_POSITIVE))
    if value > _MAX_QUERY_LIMIT:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_LIMIT_TOO_LARGE))
    return value


def normalize_project_path(value: str, cwd: Path | None = None) -> Path:
    normalized = value.strip()
    if not normalized:
        raise ValueError(i18n.t(Keys.QUERY_ERROR_EMPTY_PATH))

    path = Path(normalized).expanduser()
    if not path.is_absolute():
        base_dir = cwd if cwd is not None else Path.cwd()
        path = base_dir / path
    return path.resolve(strict=False)


def extract_session_working_directory(session: Session) -> Path | None:
    working_directory = derive_session_facts(session).working_directory
    if working_directory is None:
        return None
    return normalize_project_path(str(working_directory))


def is_path_scope_match(project_path: Path, session_path: Path) -> bool:
    return session_path == project_path or project_path in session_path.parents or session_path in project_path.parents


def filter_sessions_by_query(agent: BaseAgent, sessions: list[Session], spec: QuerySpec | None) -> list[Session]:
    """Apply structured query spec to one agent's sessions."""
    if spec is None:
        return sessions
    return [match.session for match in query_session_matches(agent, sessions, spec)]


def _contains_structured_query_terms(query: str) -> bool:
    for token in query.split():
        key, separator, _ = token.partition(":")
        if not separator:
            continue
        if key.strip().lower() in STRUCTURED_QUERY_KEYS:
            return True
    return False


def _parse_structured_query(raw: str, valid_agents: set[str]) -> QuerySpec:
    keyword_terms: list[str] = []
    agent_names: set[str] | None = None
    roles: set[str] | None = None
    project_path: Path | None = None
    limit: int | None = None

    for token in raw.split():
        key, separator, value = token.partition(":")
        if not separator:
            keyword_terms.append(token)
            continue

        normalized_key = key.strip().lower()
        if normalized_key not in STRUCTURED_QUERY_KEYS:
            raise ValueError(i18n.t(Keys.QUERY_ERROR_UNKNOWN_FIELD, field=key.strip()))

        normalized_value = value.strip()
        if normalized_key == "provider":
            agent_names = _parse_provider_scope(normalized_value, valid_agents)
            continue
        if normalized_key == "role":
            roles = _parse_roles(normalized_value)
            continue
        if normalized_key in QUERY_PATH_KEYS:
            if project_path is not None:
                raise ValueError(i18n.t(Keys.QUERY_ERROR_DUPLICATE_PATH))
            project_path = normalize_project_path(normalized_value)
            continue
        if normalized_key == "limit":
            if limit is not None:
                raise ValueError(i18n.t(Keys.QUERY_ERROR_DUPLICATE_LIMIT))
            limit = _parse_limit(normalized_value)
            continue

    keyword = " ".join(keyword_terms).strip() or None
    return QuerySpec(
        agent_names=agent_names,
        keyword=keyword,
        project_path=project_path,
        roles=roles,
        limit=limit,
    )


def _filter_sessions_from_source_or_data(
    agent: BaseAgent,
    sessions: list[Session],
    query: TextQuery,
) -> list[Session]:
    matched: list[Session] = []
    for session in sessions:
        content = extract_session_searchable_text_once(agent, session)
        fields = (session.title,) if content is None else (session.title, content)
        if query.matches(fields):
            matched.append(session)

    return matched


def _role_search_matches(
    agent: BaseAgent,
    sessions: list[Session],
    roles: set[str],
    query: TextQuery | None,
    *,
    limit: int | None,
) -> list[SearchSessionMatch]:
    candidates = (
        sessions if limit is None else sorted(sessions, key=lambda session: _query_session_sort_key(agent, session))
    )
    matches: list[SearchSessionMatch] = []
    for session in candidates:
        evidence = _find_role_evidence(agent, session, roles, query)
        if evidence is None:
            continue
        role, snippet = evidence
        matches.append(
            SearchSessionMatch(
                agent=agent,
                session=session,
                snippet=snippet,
                rank=0.0,
                matched_role=role,
            )
        )
        if limit is not None and len(matches) >= limit:
            break

    return matches


def _find_role_evidence(
    agent: BaseAgent,
    session: Session,
    roles: set[str],
    query: TextQuery | None,
) -> tuple[str, str] | None:
    try:
        with agent.lease_cached_session_data(session) as session_data:
            messages = session_data.get("messages")
            if not isinstance(messages, list):
                return None

            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "")).strip().lower()
                if role not in roles:
                    continue
                text = _extract_message_search_text(message)
                if query is None:
                    return role, _build_evidence_excerpt(text)
                if evidence := query.find_match((text,)):
                    return role, evidence.snippet
    except Exception as exc:  # noqa: BLE001 - 单个坏会话不应中断查询，但结果不完整必须告警
        print(
            render_terminal_message(
                Keys.WARN_SESSION_READ_SKIPPED,
                uri=agent.get_session_uri(session),
                error=exc,
            ),
            file=sys.stderr,
        )
        return None

    return None


def _extract_message_search_text(message: dict[str, Any]) -> str:
    return "\n".join(read_message(message).searchable_texts)


def _query_evidence_sort_key(match: SearchSessionMatch) -> tuple[float, float, str, str]:
    return _query_session_sort_key(match.agent, match.session)


def _query_session_sort_key(agent: BaseAgent, session: Session) -> tuple[float, float, str, str]:
    updated_at = normalize_datetime_utc(session.updated_at)
    created_at = normalize_datetime_utc(session.created_at)
    return (
        -updated_at.timestamp(),
        -created_at.timestamp(),
        agent.name,
        session.id,
    )


def _search_match_sort_key(match: SearchSessionMatch) -> tuple[float, float, float, str, str]:
    updated_at = normalize_datetime_utc(match.session.updated_at)
    created_at = normalize_datetime_utc(match.session.created_at)
    return (-match.rank, -updated_at.timestamp(), -created_at.timestamp(), match.agent.name, match.session.id)


def _try_indexed_search_matches(
    agent: BaseAgent,
    all_sessions: list[Session],
    scoped_sessions: list[Session],
    query: TextQuery,
    limit: int | None = None,
) -> list[SearchSessionMatch] | None:
    """Try indexed search while retaining SearchResult metadata."""
    try:
        index = SearchIndex()
        if not index.is_available:
            return None

        index.update(agent, all_sessions)
        scoped_by_id = {session.id: session for session in scoped_sessions}
        results = index.search(query, agent_names={agent.name}, limit=limit)
        matches: list[SearchSessionMatch] = []
        for result in results:
            session = scoped_by_id.get(result.session_id)
            if session is None:
                continue
            snippet = result.snippet or query.build_snippet((session.title,)) or session.title
            matches.append(
                SearchSessionMatch(
                    agent=agent,
                    session=session,
                    snippet=snippet,
                    rank=result.rank,
                )
            )
        return matches
    except Exception as exc:  # noqa: BLE001 - 索引出问题时退回文件扫描，但必须让用户看见
        _warn_index_unusable(agent, exc)
        return None


def _warn_index_unusable(agent: BaseAgent, exc: BaseException) -> None:
    """Report a real index failure instead of silently degrading to a file scan.

    「索引不可用」（SQLite 没编译 FTS5）与「索引出错」（库被锁、损坏、写失败）此前都被
    同一个 except Exception 吞掉并当作前者，于是坏索引永远不会被报告，也就永远不会被
    重建。这里仍然宽捕获——退回文件扫描比让整条命令崩掉更有用——但一定告警，
    区别只在于：不可用是静默的正常状态，出错是要说出来的异常状态。
    """
    print(
        render_terminal_message(
            Keys.WARN_INDEX_UNUSABLE,
            agent=agent.display_name,
            error_type=type(exc).__name__,
            error=exc,
        ),
        file=sys.stderr,
    )


def _fallback_search_matches(
    agent: BaseAgent,
    sessions: list[Session],
    query: TextQuery | str,
) -> list[SearchSessionMatch]:
    text_query = query if isinstance(query, TextQuery) else TextQuery.parse(query, TextQueryMode.SEARCH_TERMS)
    matches: list[SearchSessionMatch] = []
    for session in sessions:
        content = extract_session_searchable_text_once(agent, session)
        fields = (session.title,) if content is None else (session.title, content)
        evidence = text_query.find_match(fields)
        if evidence is None:
            continue
        rank = 1.0 if 0 in evidence.fully_matching_field_indexes else 0.0
        matches.append(SearchSessionMatch(agent=agent, session=session, snippet=evidence.snippet, rank=rank))

    return matches


def _build_evidence_excerpt(text: str, context_chars: int = 96) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= context_chars:
        return normalized
    return normalized[:context_chars].rstrip() + "..."


def _try_indexed_search(agent: BaseAgent, sessions: list[Session], query: TextQuery) -> list[Session] | None:
    """Try using the local search index. Returns None to fall back."""
    try:
        index = SearchIndex()
        if not index.is_available:
            return None

        index.update(agent, sessions)
        results = index.search(query, agent_names={agent.name})
        matched_ids = {r.session_id for r in results}
        return [s for s in sessions if s.id in matched_ids]
    except Exception as exc:  # noqa: BLE001 - 索引出问题时退回文件扫描，但必须让用户看见
        _warn_index_unusable(agent, exc)
        return None
