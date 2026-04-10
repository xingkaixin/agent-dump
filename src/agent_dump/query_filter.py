"""
Query parsing and session filtering helpers.
"""

from contextlib import suppress
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs, urlparse

from agent_dump.agents.base import BaseAgent, Session

AGENT_ALIASES = {
    "claude": "claudecode",
}


@dataclass(frozen=True)
class QuerySpec:
    """Parsed query option."""

    agent_names: set[str] | None
    keyword: str | None
    project_path: Path | None


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
        raise ValueError("查询条件不能为空")

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
                raise ValueError(f"未知 agent 名称: {unknown}")

            if not keyword:
                raise ValueError("查询关键词不能为空")

            return QuerySpec(agent_names=normalized_agents, keyword=keyword, project_path=None)

    return QuerySpec(agent_names=None, keyword=query, project_path=None)


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

    if keyword is not None:
        keyword = keyword.strip()
        if not keyword:
            keyword = None

    agent_names = _parse_provider_scope(providers, valid_agents) if providers is not None else None
    return QuerySpec(agent_names=agent_names, keyword=keyword, project_path=project_path)


def filter_sessions(agent: BaseAgent, sessions: list[Session], keyword: str | None) -> list[Session]:
    """Filter sessions by keyword for one agent."""
    query = (keyword or "").strip().lower()
    if not query:
        return sessions
    if not sessions:
        return []

    if agent.name == "opencode":
        return _filter_opencode_sessions(agent, sessions, query)

    return _filter_sessions_from_source_or_data(agent, sessions, query)


def _normalize_agent_name(name: str, valid_agents: set[str]) -> str | None:
    normalized = AGENT_ALIASES.get(name, name)
    if normalized in valid_agents:
        return normalized
    return None


def _parse_query_uri_project_path(parsed_uri, cwd: Path | None) -> Path:
    raw_path = f"{parsed_uri.netloc}{parsed_uri.path}".strip()
    if not raw_path:
        raise ValueError("查询路径不能为空")
    return normalize_project_path(raw_path, cwd=cwd)


def _extract_single_query_param(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[-1]


def _parse_provider_scope(raw: str, valid_agents: set[str]) -> set[str]:
    provider_names = [name.strip().lower() for name in raw.split(",") if name.strip()]
    if not provider_names:
        raise ValueError("providers 不能为空")

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
        raise ValueError(f"未知 agent 名称: {unknown}")

    return normalized_agents


def normalize_project_path(value: str, cwd: Path | None = None) -> Path:
    normalized = value.strip()
    if not normalized:
        raise ValueError("查询路径不能为空")

    path = Path(normalized).expanduser()
    if not path.is_absolute():
        base_dir = cwd if cwd is not None else Path.cwd()
        path = base_dir / path
    return path.resolve(strict=False)


def extract_session_project_path(session: Session) -> Path | None:
    raw_path = str(session.metadata.get("cwd") or session.metadata.get("directory") or "").strip()
    if not raw_path:
        return None
    return normalize_project_path(raw_path)


def is_path_scope_match(project_path: Path, session_path: Path) -> bool:
    return session_path == project_path or project_path in session_path.parents or session_path in project_path.parents


def filter_sessions_by_query(agent: BaseAgent, sessions: list[Session], spec: QuerySpec | None) -> list[Session]:
    """Apply structured query spec to one agent's sessions."""
    if spec is None:
        return sessions
    if spec.agent_names is not None and agent.name not in spec.agent_names:
        return []

    filtered = sessions
    if spec.project_path is not None:
        filtered = [
            session
            for session in filtered
            if (
                (session_path := extract_session_project_path(session)) is not None
                and is_path_scope_match(spec.project_path, session_path)
            )
        ]

    if spec.keyword is not None:
        filtered = filter_sessions(agent, filtered, spec.keyword)

    return filtered


def _filter_opencode_sessions(agent: BaseAgent, sessions: list[Session], keyword: str) -> list[Session]:
    db_path = getattr(agent, "db_path", None)
    if not isinstance(db_path, Path):
        return _filter_sessions_from_source_or_data(agent, sessions, keyword)

    like_pattern = f"%{keyword}%"
    matched_ids: set[str] = set()
    session_ids = [session.id for session in sessions]

    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        for chunk in _chunk_ids(session_ids, size=200):
            cursor.execute(
                """
                SELECT DISTINCT s.id
                FROM session s
                LEFT JOIN message m ON m.session_id = s.id
                LEFT JOIN part p ON p.message_id = m.id
                WHERE s.id IN (SELECT value FROM json_each(?))
                  AND (
                    LOWER(COALESCE(s.title, '')) LIKE ?
                    OR LOWER(COALESCE(m.data, '')) LIKE ?
                    OR LOWER(COALESCE(p.data, '')) LIKE ?
                  )
                """,
                [json.dumps(chunk), like_pattern, like_pattern, like_pattern],
            )
            matched_ids.update(str(row["id"]) for row in cursor.fetchall())
    except Exception:
        return _filter_sessions_from_source_or_data(agent, sessions, keyword)
    finally:
        if conn is not None:
            with suppress(Exception):
                conn.close()

    return [session for session in sessions if session.id in matched_ids]


def _chunk_ids(ids: list[str], size: int) -> list[list[str]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def _filter_sessions_from_source_or_data(agent: BaseAgent, sessions: list[Session], keyword: str) -> list[Session]:
    matched: list[Session] = []
    for session in sessions:
        if _match_title(session, keyword):
            matched.append(session)
            continue

        if _has_searchable_source(session.source_path):
            if _match_source_file(session.source_path, keyword):
                matched.append(session)
            continue

        if _match_session_data(agent, session, keyword):
            matched.append(session)

    return matched


def _match_title(session: Session, keyword: str) -> bool:
    return keyword in session.title.lower()


def _has_searchable_source(source_path: Path) -> bool:
    if source_path.is_file():
        return _is_searchable_text_file(source_path)

    if not source_path.is_dir():
        return False

    wire_file = source_path / "wire.jsonl"
    if wire_file.exists():
        return _is_searchable_text_file(wire_file)

    return any(_is_searchable_text_file(jsonl_file) for jsonl_file in source_path.glob("*.jsonl"))


def _is_searchable_text_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in {".jsonl", ".json", ".md", ".txt", ".log"}


def _match_source_file(source_path: Path, keyword: str) -> bool:
    try:
        if source_path.is_file():
            return _file_contains(source_path, keyword)
        if source_path.is_dir():
            wire_file = source_path / "wire.jsonl"
            if wire_file.exists():
                return _file_contains(wire_file, keyword)

            for jsonl_file in source_path.glob("*.jsonl"):
                if _file_contains(jsonl_file, keyword):
                    return True
    except Exception:
        return False

    return False


def _file_contains(file_path: Path, keyword: str) -> bool:
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if keyword in line.lower():
                return True
    return False


def _match_session_data(agent: BaseAgent, session: Session, keyword: str) -> bool:
    try:
        session_data = agent.get_session_data(session)
    except Exception:
        return False

    content = json.dumps(session_data, ensure_ascii=False)
    return keyword in content.lower()
