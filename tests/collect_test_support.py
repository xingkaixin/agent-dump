from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from agent_dump.agents.base import Session
from agent_dump.query_filter import QuerySpec


def make_query_spec(
    *,
    agent_names: set[str] | None = None,
    keyword: str | None = None,
    project_path: Path | None = None,
    roles: set[str] | None = None,
    limit: int | None = None,
) -> QuerySpec:
    return QuerySpec(
        agent_names=frozenset(agent_names) if agent_names is not None else None,
        keyword=keyword,
        project_path=project_path,
        roles=frozenset(roles) if roles is not None else None,
        limit=limit,
    )


def configure_session_data_lease(agent: mock.MagicMock) -> None:
    @contextmanager
    def lease(session: Session):
        yield agent.get_cached_session_data(session)

    agent.lease_cached_session_data.side_effect = lease
