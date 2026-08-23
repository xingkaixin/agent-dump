"""Shared builders for CLI workflow tests."""

import argparse
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

from agent_dump.agents.base import Session, derive_session_facts
from agent_dump.collect_models import CollectMode
from agent_dump.command_plan import CollectOperation, CommandRequest, build_command_plan
from agent_dump.config import CollectConfig
from agent_dump.exporting import ExportRunStatus


def make_export_result(*paths: Path) -> mock.MagicMock:
    result = mock.MagicMock()
    result.exported_paths = paths
    result.status = ExportRunStatus.SUCCEEDED if paths else ExportRunStatus.FAILED
    result.__len__.return_value = len(paths)
    return result


def make_config_document(
    *,
    ai_config: object | None = None,
    collect_config: object | None = None,
    logging_config: object | None = None,
) -> mock.MagicMock:
    document = mock.MagicMock()
    document.ai_config.return_value = ai_config
    document.collect_config.return_value = collect_config if collect_config is not None else CollectConfig()
    document.logging_config.return_value = logging_config if logging_config is not None else mock.MagicMock()
    return document


def collect_operation_from(args: argparse.Namespace) -> CollectOperation:
    plan = build_command_plan(
        CommandRequest(
            collect=True,
            uri=getattr(args, "uri", None),
            days=getattr(args, "days", None),
            interactive=getattr(args, "interactive", False),
            list_requested=getattr(args, "list", False),
            since=getattr(args, "since", None),
            until=getattr(args, "until", None),
            save=getattr(args, "save", None),
            dry_run=getattr(args, "dry_run", False),
            collect_mode=CollectMode(getattr(args, "collect_mode", CollectMode.PM)),
        )
    )
    assert isinstance(plan.operation, CollectOperation)
    return plan.operation


def configure_scanner_sessions(scanner: mock.MagicMock) -> None:
    scanner.get_sessions.side_effect = lambda days=7, *, agents=None: [
        (agent, agent.get_sessions(days=days))
        for agent in (agents if agents is not None else scanner.get_available_agents.return_value)
    ]


def configure_session_data_lease(agent: mock.MagicMock) -> None:
    agent.get_session_facts.side_effect = derive_session_facts

    @contextmanager
    def lease(session: Session):
        yield agent.get_cached_session_data(session)

    agent.lease_cached_session_data.side_effect = lease


def make_session(
    session_id: str,
    title: str,
    *,
    created_at: datetime | None = None,
    source_path: Path | None = None,
    metadata: dict | None = None,
) -> Session:
    """构造测试用 Session。"""
    session_time = created_at or datetime(2026, 1, 1, 12, 0, 0)
    return Session(
        id=session_id,
        title=title,
        created_at=session_time,
        updated_at=session_time,
        source_path=source_path or Path(f"/tmp/{session_id}.jsonl"),
        metadata=metadata or {},
    )
