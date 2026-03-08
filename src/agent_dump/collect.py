"""Collect mode: gather sessions and summarize with LLM."""

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
import json
from pathlib import Path
from typing import Any
from urllib import error, request

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.config import AIConfig
from agent_dump.time_utils import get_local_timezone, get_local_today, normalize_datetime_utc, to_local_datetime

SUPPORTED_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d")
MAX_SESSION_TEXT_CHARS = 8000


@dataclass(frozen=True)
class CollectEntry:
    """One collected session text entry."""

    date_value: date
    created_at: datetime
    agent_name: str
    agent_display_name: str
    session_id: str
    session_title: str
    session_uri: str
    project_directory: str
    text: str


def parse_user_date(value: str) -> date:
    """Parse date from supported input formats."""
    normalized = value.strip()
    for fmt in SUPPORTED_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    raise ValueError(f"invalid date format: {value}")


def resolve_collect_date_range(
    since: str | None,
    until: str | None,
    *,
    today: date | None = None,
    local_tz: tzinfo | None = None,
) -> tuple[date, date]:
    """Resolve effective [since, until] date range."""
    effective_today = today or get_local_today(local_tz)

    if not since and not until:
        return effective_today, effective_today

    if since and until:
        start = parse_user_date(since)
        end = parse_user_date(until)
        if start > end:
            raise ValueError("since_after_until")
        return start, end

    if since:
        start = parse_user_date(since)
        end = effective_today
        if start > end:
            raise ValueError("since_after_until")
        return start, end

    # only until exists
    end = parse_user_date(until or "")
    start = date(end.year, end.month, 1)
    if start > end:
        raise ValueError("since_after_until")
    return start, end


def _session_local_date(session: Session, local_tz: tzinfo) -> date:
    return to_local_datetime(session.created_at, local_tz).date()


def _truncate(text: str, limit: int = MAX_SESSION_TEXT_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def collect_entries(
    *,
    agents: list[BaseAgent],
    since_date: date,
    until_date: date,
    render_session_text_fn,
    local_tz: tzinfo | None = None,
) -> tuple[list[CollectEntry], bool]:
    """Collect and render session text entries for range."""
    entries: list[CollectEntry] = []
    has_truncated = False
    resolved_local_tz = local_tz or get_local_timezone()

    for agent in agents:
        days_span = max((get_local_today(resolved_local_tz) - since_date).days + 1, 1)
        sessions = agent.get_sessions(days=days_span)

        for session in sessions:
            session_date = _session_local_date(session, resolved_local_tz)
            if session_date < since_date or session_date > until_date:
                continue

            session_data: dict[str, Any] = agent.get_session_data(session)
            uri = agent.get_session_uri(session)
            rendered = render_session_text_fn(uri, session_data)
            trimmed, truncated = _truncate(rendered)
            has_truncated = has_truncated or truncated

            entries.append(
                CollectEntry(
                    date_value=session_date,
                    created_at=session.created_at,
                    agent_name=agent.name,
                    agent_display_name=agent.display_name,
                    session_id=session.id,
                    session_title=session.title,
                    session_uri=uri,
                    project_directory=str(session.metadata.get("cwd") or session.metadata.get("directory") or ""),
                    text=trimmed,
                )
            )

    entries.sort(key=lambda item: normalize_datetime_utc(item.created_at))
    return entries, has_truncated


def build_collect_prompt(
    *,
    since_date: date,
    until_date: date,
    entries: list[CollectEntry],
    has_truncated: bool,
    local_tz: tzinfo | None = None,
) -> str:
    """Build collect summary prompt."""
    resolved_local_tz = local_tz or get_local_timezone()
    header = [
        "你是一个工作记录分析助手。",
        "请基于给定时段内的会话内容，输出 Markdown，总结重点工作。",
        "必须严格使用以下结构：",
        f"# 时段工作总结（{since_date.isoformat()} ~ {until_date.isoformat()}）",
        "## 按日期",
        "## 按项目/目录",
        "## 重点事项（决策/风险/阻塞）",
        "## 产出清单",
        "## 下一步建议",
        "要求：避免空话，按事实归纳；同一事项合并去重；可按优先级标注。",
    ]

    if has_truncated:
        header.append("注意：部分会话文本因过长被截断，请在总结中标注可能遗漏细节。")

    lines = ["", "以下是原始会话素材："]
    for index, entry in enumerate(entries, start=1):
        lines.extend(
            [
                "",
                f"### Session {index}",
                f"- 日期: {entry.date_value.isoformat()}",
                f"- 时间: {to_local_datetime(entry.created_at, resolved_local_tz).isoformat()}",
                f"- Agent: {entry.agent_display_name} ({entry.agent_name})",
                f"- URI: {entry.session_uri}",
                f"- 标题: {entry.session_title}",
                f"- 项目目录: {entry.project_directory or '(unknown)'}",
                "- 内容:",
                entry.text,
            ]
        )

    return "\n".join(header + lines)


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def request_summary_from_llm(config: AIConfig, prompt: str, *, timeout_seconds: int = 90) -> str:
    """Call provider API and return markdown summary."""
    if config.provider == "openai":
        return _request_openai(config, prompt, timeout_seconds=timeout_seconds)
    if config.provider == "anthropic":
        return _request_anthropic(config, prompt, timeout_seconds=timeout_seconds)
    raise RuntimeError(f"Unsupported provider: {config.provider}")


def _request_openai(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的工作总结助手。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    body = json.dumps(payload).encode("utf-8")
    url = f"{_normalize_base_url(config.base_url)}/chat/completions"
    req = request.Request(  # noqa: S310
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("OpenAI API response missing content") from exc

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI API returned empty content")
    return content


def _request_anthropic(config: AIConfig, prompt: str, *, timeout_seconds: int) -> str:
    payload = {
        "model": config.model,
        "max_tokens": 4096,
        "system": "你是一个严谨的工作总结助手。",
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    url = f"{_normalize_base_url(config.base_url)}/messages"
    req = request.Request(  # noqa: S310
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") if exc.fp else str(exc)
        raise RuntimeError(f"Anthropic API HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

    content_items = data.get("content")
    if not isinstance(content_items, list):
        raise RuntimeError("Anthropic API response missing content")

    texts = [item.get("text", "") for item in content_items if isinstance(item, dict) and item.get("type") == "text"]
    content = "\n".join(part for part in texts if part)

    if not content.strip():
        raise RuntimeError("Anthropic API returned empty content")
    return content


def write_collect_markdown(markdown: str, *, output_dir: Path | None = None, today: date | None = None) -> Path:
    """Write collect markdown file to current directory."""
    resolved_today = today or get_local_today()
    base = output_dir if output_dir is not None else Path.cwd()
    path = base / f"agent-dump-collect-{resolved_today.strftime('%Y%m%d')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
