"""
Cursor agent handler
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, cast

from agent_dump.agents.base import BaseAgent, Session
from agent_dump.agents.message_types import NormalizedSessionData
from agent_dump.coercion import safe_epoch_datetime, safe_float, safe_int
from agent_dump.diagnostics import DiagnosticError, source_missing, unsupported_capability
from agent_dump.i18n import Keys, i18n
from agent_dump.paths import SearchRoot
from agent_dump.time_utils import normalize_datetime_utc

_EPOCH_UTC = datetime.fromtimestamp(0, tz=timezone.utc)


def _parse_cursor_iso_utc(value: str) -> datetime | None:
    """Parse one Cursor ISO timestamp as UTC, or None when it is not ISO.

    Cursor 的 ISO 字段可能不带 offset。naive datetime 交给 astimezone() 或
    timestamp() 会先按主机本地时区解释，同一份数据在 UTC 与 Asia/Shanghai 相差
    8 小时；Session 时间和 bubble 时间必须共用这一个转换事实。
    """
    try:
        return normalize_datetime_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _key_prefix_bounds(prefix: str) -> tuple[str, str]:
    """Return [lower, upper) bounds equivalent to `key LIKE '{prefix}%'`.

    Range comparisons use the primary-key index, while LIKE with the default
    case-insensitive collation forces a full table scan per query.
    """
    return prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)


# bubbleId:<composer_id>:<bubble_id> —— "bubbleId:" 长 9，故 composer_id 从第 10 个字符起，
# 长度到其后第一个 ':' 为止。写成字面量，不做字符串拼接。
#
# 关键取舍：json_extract 只出现在 WHERE 里、输出仅 COUNT(*) 时约 0.3s/5 万 bubble；
# 一旦让它出现在输出列（哪怕配 MIN(key) 取首个非空值），同样的数据要 3.7s——比在
# Python 侧 json.loads 还慢。所以只有计数交给 SQL，取值仍在 Python 做。
_BUBBLE_MESSAGE_COUNT_SQL = """
    SELECT substr(key, 10, instr(substr(key, 10), ':') - 1) AS composer_id,
           COUNT(*) AS message_count
    FROM cursorDiskKV
    WHERE ({key_ranges}) AND json_extract(value, '$.type') IN (1, 2)
    GROUP BY composer_id
"""

# 一条 SQL 里最多放多少个 composer 的 key range。计数查询的每个 range 占 2 个
# 绑定参数和一层 OR 节点，元数据查询每个 range 占 4 个绑定参数和一个
# compound term；批过大会撞上 SQLite 的变量数、表达式深度或 compound-select 上限。
_BUBBLE_RANGE_BATCH_SIZE = 100

# 列表元数据只需要首个带 requestId 的 bubble 和首个带 modelInfo.modelName 的 bubble，
# 二者在真实数据里都出现在会话开头。取前 N 条足够，避免为两个字段搬运整段会话正文。
_METADATA_BUBBLE_SCAN_LIMIT = 20


class CursorAgent(BaseAgent):
    """Handler for Cursor sessions stored in SQLite."""

    # Cursor 会话没有独立原始文件，markdown 渲染也未适配其数据形态
    unsupported_uri_formats = frozenset({"raw", "markdown"})

    def __init__(self) -> None:
        super().__init__("cursor", "Cursor")

    def _default_cursor_user_root(self) -> Path:
        home = Path.home()
        if os.name == "nt":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "Cursor" / "User"
            return home / "AppData" / "Roaming" / "Cursor" / "User"
        if sys_platform_startswith("darwin"):
            return home / "Library" / "Application Support" / "Cursor" / "User"
        return home / ".config" / "Cursor" / "User"

    def _find_global_db_path(self) -> Path:
        return self._default_cursor_user_root() / "globalStorage" / "state.vscdb"

    def get_search_roots(self) -> tuple[SearchRoot, ...]:
        return (SearchRoot("Cursor global state.vscdb", self._find_global_db_path()),)

    def is_available(self) -> bool:
        """Cursor is readable exactly when its global store opens read-only.

        每一条会话读取都只走 globalStorage/state.vscdb，所以可用性也只能由它决定。
        路径是从环境纯计算出来的，不缓存成实例状态：曾经只有 is_available() 会写
        global_db_path，于是 fresh get_sessions() 返回空，而先调 is_available()
        的同一实例反而能读到数据。
        """
        db_path = self._find_global_db_path()
        if not db_path.exists():
            return False
        try:
            # 仅 exists() 不足以判定可读：损坏文件或缺少权限时读取会在更深处失败，
            # 到那时 Scanner 已经把 Cursor 当作可用 Provider 报告出去了
            sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True).close()
        except (sqlite3.Error, OSError):
            return False
        return True

    def _missing_global_db_error(self) -> DiagnosticError:
        return source_missing(
            "Cursor global database is missing",
            missing_path=self._find_global_db_path(),
            searched_roots=[root.render() for root in self.get_search_roots()],
            next_steps=(
                i18n.t(Keys.DIAG_STEP_CURSOR_DB_EXISTS),
                i18n.t(Keys.DIAG_STEP_CURSOR_LIST_TO_CHECK),
            ),
        )

    @contextmanager
    def _open_global(self) -> Iterator[sqlite3.Connection]:
        """Open one read-only connection to the global store."""
        db_path = self._find_global_db_path()
        if not db_path.exists():
            raise self._missing_global_db_error()

        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _query_global(
        self, sql: str, params: tuple[Any, ...], *, conn: sqlite3.Connection | None = None
    ) -> list[sqlite3.Row]:
        """Run one query, reusing `conn` when the caller already holds one.

        每次调用都新建连接的话，一次列表操作会为每个会话各开一个连接并做一次
        path.resolve()；调用方在循环外持有连接即可省掉这笔固定开销。
        """
        if conn is not None:
            return conn.execute(sql, params).fetchall()
        with self._open_global() as owned:
            return owned.execute(sql, params).fetchall()

    def _parse_json(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if not isinstance(raw, str):
            return None
        if not raw.strip():
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _get_bubble_rows(self, composer_id: str, *, conn: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
        lower, upper = _key_prefix_bounds(f"bubbleId:{composer_id}:")
        return self._query_global(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key",
            (lower, upper),
            conn=conn,
        )

    def _extract_title(self, composer: dict[str, Any], composer_id: str) -> str:
        name = composer.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        title = composer.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return f"Cursor Session {composer_id[:8]}"

    def _parse_datetime_utc(self, value: Any) -> datetime | None:
        if isinstance(value, str) and "T" in value:
            parsed = _parse_cursor_iso_utc(value)
            if parsed is not None:
                return parsed
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            number = safe_float(value, default=float("nan"))
            # Cursor 同一字段既可能存秒也可能存毫秒，1e12 秒约合公元 33658 年，
            # 超过即判定为毫秒
            unit = "ms" if number > 1e12 else "s"
            return safe_epoch_datetime(number, unit=unit)
        return None

    def _resolve_session_times(self, composer: dict[str, Any]) -> tuple[datetime, datetime]:
        """Resolve created/updated times; unknown timestamps degrade to epoch instead of 'now'."""
        created = self._parse_datetime_utc(composer.get("createdAt"))
        updated_raw = composer.get("updatedAt") or composer.get("lastUpdatedAt") or composer.get("lastSendTime")
        updated = self._parse_datetime_utc(updated_raw)
        created_at = created or updated or _EPOCH_UTC
        return created_at, (updated or created_at)

    def _build_session_metadata(self, composer: dict[str, Any], *, composer_id: str, request_id: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "composer_id": composer_id,
            "request_id": request_id,
            "parent_composer_id": None,
            "subagent_composer_ids": [],
            "usage_data": composer.get("usageData"),
            "model": self._extract_composer_model(composer),
            "message_count": 0,
        }
        subagent_info = composer.get("subagentInfo")
        if isinstance(subagent_info, dict):
            parent_id = subagent_info.get("parentComposerId")
            if isinstance(parent_id, str) and parent_id:
                metadata["parent_composer_id"] = parent_id
        sub_ids = composer.get("subagentComposerIds")
        if isinstance(sub_ids, list):
            metadata["subagent_composer_ids"] = [str(x) for x in sub_ids if isinstance(x, str)]
        return metadata

    def _extract_composer_model(self, composer: dict[str, Any]) -> str | None:
        model_config = composer.get("modelConfig")
        if isinstance(model_config, dict):
            model_name = model_config.get("modelName")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()
        return None

    def _count_messages_by_composer(self, conn: sqlite3.Connection, composer_ids: list[str]) -> dict[str, int] | None:
        """Count user/assistant bubbles for exactly these composers.

        逐会话统计要把所有 bubble 的完整正文搬进 Python 再 json.loads，只为得到一个
        计数。JSON1 自 SQLite 3.38 起内建，老版本缺失时 json_extract 抛
        OperationalError，此时返回 None 让调用方退回逐会话路径。

        只统计传入的 composer：每个 composer 的 bubble key 各占一段连续 range，
        SQLite 对 OR 组合的 range 走 MULTI-INDEX OR，逐段用主键索引定位。扫整个
        `bubbleId:` 前缀会让 days=1 也付出全部历史 bubble 的代价。
        """
        counts: dict[str, int] = {}
        for start in range(0, len(composer_ids), _BUBBLE_RANGE_BATCH_SIZE):
            batch = composer_ids[start : start + _BUBBLE_RANGE_BATCH_SIZE]
            params: list[str] = []
            for composer_id in batch:
                params.extend(_key_prefix_bounds(f"bubbleId:{composer_id}:"))
            key_ranges = " OR ".join("(key >= ? AND key < ?)" for _ in batch)
            try:
                rows = conn.execute(_BUBBLE_MESSAGE_COUNT_SQL.format(key_ranges=key_ranges), params).fetchall()
            except sqlite3.OperationalError:
                return None
            for row in rows:
                counts[str(row["composer_id"])] = safe_int(row["message_count"])
        return counts

    def _scan_metadata_bubbles_by_composer(
        self,
        composer_ids: list[str],
        *,
        conn: sqlite3.Connection,
    ) -> dict[str, tuple[str | None, str | None]]:
        """Read request ids and models from a bounded prefix of each composer's bubbles."""
        summaries: dict[str, tuple[str | None, str | None]] = {}
        for start in range(0, len(composer_ids), _BUBBLE_RANGE_BATCH_SIZE):
            batch = composer_ids[start : start + _BUBBLE_RANGE_BATCH_SIZE]
            statements: list[str] = []
            params: list[str | int] = []
            for composer_id in batch:
                lower, upper = _key_prefix_bounds(f"bubbleId:{composer_id}:")
                statements.append(
                    "SELECT * FROM ("
                    "SELECT ? AS composer_id, key, value FROM cursorDiskKV "
                    "WHERE key >= ? AND key < ? ORDER BY key LIMIT ?"
                    ")"
                )
                params.extend((composer_id, lower, upper, _METADATA_BUBBLE_SCAN_LIMIT))

            rows = conn.execute(" UNION ALL ".join(statements) + " ORDER BY composer_id, key", params).fetchall()
            for row in rows:
                composer_id = str(row["composer_id"])
                request_id, model = summaries.get(composer_id, (None, None))
                bubble = self._parse_json(row["value"])
                if not bubble:
                    continue
                if request_id is None:
                    raw_request_id = bubble.get("requestId")
                    if isinstance(raw_request_id, str) and raw_request_id.strip():
                        request_id = raw_request_id.strip()
                if model is None:
                    model_info = bubble.get("modelInfo")
                    model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
                    if isinstance(model_name, str) and model_name.strip():
                        model = model_name.strip()
                summaries[composer_id] = (request_id, model)
        return summaries

    def _summarize_bubbles(self, bubble_rows: list[sqlite3.Row]) -> tuple[str | None, int, str | None]:
        """Return (request_id, message_count, model) from a single pass over the rows.

        JSON1 缺失时的回退路径。之前取 requestId 与统计元数据
        各自完整遍历并 json.loads 一遍同一批 bubble，等于每条 bubble 解析两次。
        """
        request_id: str | None = None
        message_count = 0
        model: str | None = None

        for row in bubble_rows:
            bubble = self._parse_json(row["value"])
            if not bubble:
                continue

            if bubble.get("type") in {1, 2}:
                message_count += 1

            if request_id is None:
                raw_request_id = bubble.get("requestId")
                if isinstance(raw_request_id, str) and raw_request_id.strip():
                    request_id = raw_request_id.strip()

            if model is None:
                model_info = bubble.get("modelInfo")
                model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
                if isinstance(model_name, str) and model_name.strip():
                    model = model_name.strip()

        return request_id, message_count, model

    def _apply_bubble_summary(self, metadata: dict[str, Any], *, message_count: int, model: str | None) -> None:
        metadata["message_count"] = message_count
        metadata["model"] = metadata.get("model") or model

    def _augment_session_metadata_from_bubbles(self, metadata: dict[str, Any], bubble_rows: list[sqlite3.Row]) -> None:
        _, message_count, model = self._summarize_bubbles(bubble_rows)
        self._apply_bubble_summary(metadata, message_count=message_count, model=model)

    def get_sessions(self, days: int | None = 7) -> list[Session]:
        """Get Cursor sessions from the requested time window."""
        global_db_path = self._find_global_db_path()
        if not global_db_path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days is not None else None
        lower, upper = _key_prefix_bounds("composerData:")
        sessions: list[Session] = []

        with self._open_global() as conn:
            rows = self._query_global(
                "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY rowid DESC",
                (lower, upper),
                conn=conn,
            )
            recent: list[tuple[str, dict[str, Any], datetime, datetime]] = []
            for row in rows:
                key = str(row["key"])
                composer_id = key.split(":", 1)[1]
                composer = self._parse_json(row["value"])
                if not composer:
                    continue

                created_at, updated_at = self._resolve_session_times(composer)
                if cutoff is not None and created_at < cutoff:
                    continue
                recent.append((composer_id, composer, created_at, updated_at))

            # 有界窗口必须先于 bubble 聚合生效，否则 days=1 也要扫过全部历史 bubble
            composer_ids = [item[0] for item in recent]
            message_counts = self._count_messages_by_composer(conn, composer_ids)
            metadata_summaries = (
                self._scan_metadata_bubbles_by_composer(composer_ids, conn=conn) if message_counts is not None else {}
            )

            for composer_id, composer, created_at, updated_at in recent:
                if message_counts is not None:
                    message_count = message_counts.get(composer_id, 0)
                    bubble_request_id, bubble_model = metadata_summaries.get(composer_id, (None, None))
                else:
                    bubble_request_id, message_count, bubble_model = self._summarize_bubbles(
                        self._get_bubble_rows(composer_id, conn=conn)
                    )
                request_id = bubble_request_id or composer_id
                metadata = self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id)
                self._apply_bubble_summary(metadata, message_count=message_count, model=bubble_model)

                sessions.append(
                    Session(
                        id=request_id,
                        title=self._extract_title(composer, composer_id),
                        created_at=created_at,
                        updated_at=updated_at,
                        source_path=global_db_path,
                        metadata=metadata,
                    )
                )
        return sessions

    def _build_session_from_composer(
        self,
        *,
        composer_id: str,
        request_id: str,
        composer: dict[str, Any],
    ) -> Session:
        session = self._build_session_from_composer_metadata(
            composer_id=composer_id,
            request_id=request_id,
            composer=composer,
        )
        self._augment_session_metadata_from_bubbles(session.metadata, self._get_bubble_rows(composer_id))
        return session

    def _build_session_from_composer_metadata(
        self,
        *,
        composer_id: str,
        request_id: str,
        composer: dict[str, Any],
    ) -> Session:
        created_at, updated_at = self._resolve_session_times(composer)
        metadata = self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id)
        return Session(
            id=request_id,
            title=self._extract_title(composer, composer_id),
            created_at=created_at,
            updated_at=updated_at,
            source_path=self._find_global_db_path(),
            metadata=metadata,
        )

    def find_session_by_request_id(self, request_id: str) -> Session | None:
        """Resolve any bubble-level requestId to its owning composer session."""
        if not self._find_global_db_path().exists():
            return None
        lower, upper = _key_prefix_bounds("bubbleId:")
        rows = self._query_global(
            "SELECT key, value FROM cursorDiskKV "
            "WHERE key >= ? AND key < ? AND instr(value, ?) > 0 ORDER BY rowid DESC",
            (lower, upper, request_id),
        )
        composer_id: str | None = None
        for row in rows:
            bubble = self._parse_json(row["value"])
            if not bubble:
                continue
            bubble_request_id = bubble.get("requestId")
            if isinstance(bubble_request_id, str) and bubble_request_id == request_id:
                key = str(row["key"])
                composer_id = key.split(":")[1]
                break
        if not composer_id:
            return None

        composer_rows = self._query_global(
            "SELECT value FROM cursorDiskKV WHERE key = ?",
            (f"composerData:{composer_id}",),
        )
        if not composer_rows:
            return None
        composer = self._parse_json(composer_rows[0]["value"])
        if not composer:
            return None
        return self._build_session_from_composer(
            composer_id=composer_id,
            request_id=request_id,
            composer=composer,
        )

    def find_session_by_id(self, session_id: str) -> Session | None:
        """Resolve request ids via bubble lookup before falling back to a full scan."""
        matched = self.find_session_by_request_id(session_id)
        if matched is not None:
            return matched
        return super().find_session_by_id(session_id)

    def get_session_uri(self, session: Session) -> str:
        """Use request id as URI anchor for Cursor."""
        request_id = session.metadata.get("request_id") or session.id
        return f"cursor://{request_id}"

    def get_formatted_title(self, session: Session) -> str:
        """Render Cursor session title in local timezone for display."""
        title = session.title[:60] + "..." if len(session.title) > 60 else session.title
        session_time = session.created_at
        if session_time.tzinfo is not None:
            session_time = session_time.astimezone()
        time_str = session_time.strftime("%Y-%m-%d %H:%M")
        return f"{title} ({time_str})"

    def _extract_timestamp(self, bubble: dict[str, Any], fallback_ms: int) -> int:
        created = bubble.get("createdAt")
        if isinstance(created, str):
            parsed = _parse_cursor_iso_utc(created)
            if parsed is not None:
                return int(parsed.timestamp() * 1000)
        timing = bubble.get("timingInfo")
        if isinstance(timing, dict):
            for key in ("clientRpcSendTime", "clientSettleTime", "clientEndTime"):
                number = safe_float(timing.get(key), default=float("nan"))
                if safe_epoch_datetime(number, unit="ms") is not None:
                    return safe_int(number, fallback_ms)
        return fallback_ms

    def _extract_text_content(self, bubble: dict[str, Any], role: str) -> str | None:
        if role == "assistant":
            text = bubble.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
        code_blocks = bubble.get("codeBlocks")
        if isinstance(code_blocks, list):
            chunks = []
            for block in code_blocks:
                if isinstance(block, dict):
                    content = block.get("content")
                    if isinstance(content, str) and content.strip():
                        chunks.append(content.strip())
            if chunks:
                return "\n\n".join(chunks)
        if role == "assistant":
            thinking = bubble.get("thinking")
            if isinstance(thinking, dict):
                thinking_text = thinking.get("text")
                if isinstance(thinking_text, str) and thinking_text.strip():
                    return thinking_text.strip()
        for key in ("text", "content", "finalText", "message", "markdown", "textDescription"):
            value = bubble.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _normalize_tool_input(self, tool_data: dict[str, Any]) -> Any:
        raw_input = tool_data.get("params")
        if raw_input is None:
            raw_input = tool_data.get("rawArgs")
        if isinstance(raw_input, str):
            try:
                return json.loads(raw_input)
            except json.JSONDecodeError:
                return {"_raw": raw_input}
        return raw_input

    def _extract_tool_status(self, tool_data: dict[str, Any]) -> str | None:
        add = tool_data.get("additionalData")
        status = add.get("status") if isinstance(add, dict) else None
        if status:
            return str(status)
        raw_status = tool_data.get("status")
        return str(raw_status) if raw_status is not None else None

    def _extract_subagent_prompt(self, arguments: Any) -> str:
        if isinstance(arguments, dict):
            prompt = arguments.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
            description = arguments.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
            return json.dumps(arguments, ensure_ascii=False, indent=2)
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments, ensure_ascii=False, indent=2)

    def _extract_subagent_type(self, arguments: Any) -> str | None:
        if not isinstance(arguments, dict):
            return None
        subagent_type = arguments.get("subagentType")
        if isinstance(subagent_type, str) and subagent_type.strip():
            return subagent_type.strip()
        return None

    def _build_plan_part(self, tool_data: dict[str, Any], timestamp_ms: int) -> dict[str, Any] | None:
        normalized_input = self._normalize_tool_input(tool_data)
        if not isinstance(normalized_input, dict):
            return None
        plan_text = normalized_input.get("plan")
        if not isinstance(plan_text, str) or not plan_text.strip():
            return None

        result = self._parse_json(tool_data.get("result"))
        output: str | None = None
        if isinstance(result, dict):
            rejected = result.get("rejected")
            if rejected not in (None, {}, []):
                output = json.dumps(rejected, ensure_ascii=False)

        approval_status = "fail"
        additional_data = tool_data.get("additionalData")
        if isinstance(additional_data, dict):
            review_data = additional_data.get("reviewData")
            if isinstance(review_data, dict):
                selected_option = str(review_data.get("selectedOption") or "").strip().lower()
                if selected_option in {"accept", "accepted", "approve", "approved"}:
                    approval_status = "success"

        return {
            "type": "plan",
            "input": plan_text.strip(),
            "output": output,
            "approval_status": approval_status,
            "time_created": timestamp_ms,
        }

    def _extract_tool_output_parts(self, output: Any, timestamp_ms: int) -> list[dict[str, Any]]:
        if isinstance(output, list):
            parts: list[dict[str, Any]] = []
            for item in output:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(
                            {
                                "type": "text",
                                "text": text.strip(),
                                "time_created": safe_int(item.get("time_created"), timestamp_ms),
                            }
                        )
            return parts
        if isinstance(output, str) and output.strip():
            return [{"type": "text", "text": output.strip(), "time_created": timestamp_ms}]
        return []

    def _load_composer_by_id(self, composer_id: str) -> dict[str, Any] | None:
        rows = self._query_global(
            "SELECT value FROM cursorDiskKV WHERE key = ?",
            (f"composerData:{composer_id}",),
        )
        if not rows:
            return None
        return self._parse_json(rows[0]["value"])

    def _extract_subagent_model(self, composer: dict[str, Any], child_data: Mapping[str, Any]) -> str | None:
        model_config = composer.get("modelConfig")
        if isinstance(model_config, dict):
            model_name = model_config.get("modelName")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()

        for message in child_data.get("messages", []):
            model_name = message.get("model")
            if isinstance(model_name, str) and model_name.strip():
                return model_name.strip()
        return None

    def _build_subagent_completion_message(
        self,
        composer_id: str,
        *,
        expanding: frozenset[str],
        subagent_memo: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        if composer_id in expanding:
            # subagentComposerId 来自 Cursor 的存储，A 引用 B 而 B 又引用 A 会让
            # 展开无限递归；环上的引用退化成普通 tool call
            return None
        if composer_id in subagent_memo:
            return subagent_memo[composer_id]

        completion = self._expand_subagent(composer_id, expanding=expanding, subagent_memo=subagent_memo)
        subagent_memo[composer_id] = completion
        return completion

    def _expand_subagent(
        self,
        composer_id: str,
        *,
        expanding: frozenset[str],
        subagent_memo: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        composer = self._load_composer_by_id(composer_id)
        if not composer:
            return None
        child_session = self._build_session_from_composer_metadata(
            composer_id=composer_id,
            request_id=composer_id,
            composer=composer,
        )
        child_data = self._build_session_data(
            child_session,
            expanding=expanding | {composer_id},
            subagent_memo=subagent_memo,
        )
        parts: list[dict[str, Any]] = []
        latest_time_created = 0
        for message in child_data.get("messages", []):
            if message.get("role") != "assistant":
                continue
            for part in message.get("parts", []):
                if part.get("type") != "text":
                    continue
                text = part.get("text")
                if not isinstance(text, str):
                    continue
                stripped = text.strip()
                if not stripped or stripped in {"[empty message]", "[corrupted message]"}:
                    continue
                part_time_created = safe_int(part.get("time_created"), safe_int(message.get("time_created")))
                parts.append(
                    {
                        "type": "text",
                        "text": stripped,
                        "time_created": part_time_created,
                    }
                )
                latest_time_created = max(latest_time_created, part_time_created)

        if not parts:
            return None

        message: dict[str, Any] = {
            "id": f"{composer_id}:subagent-output",
            "role": "assistant",
            "agent": "cursor",
            "mode": None,
            "model": self._extract_subagent_model(composer, child_data),
            "provider": None,
            "time_created": latest_time_created,
            "time_completed": None,
            "tokens": {"input": 0, "output": 0},
            "cost": 0,
            "parts": parts,
            "subagent_id": composer_id,
        }

        subagent_info = composer.get("subagentInfo")
        if isinstance(subagent_info, dict):
            type_name = subagent_info.get("subagentTypeName")
            if isinstance(type_name, str) and type_name.strip():
                message["subagent_type"] = type_name.strip()
        return message

    def _extract_subagent_id(self, tool_data: dict[str, Any], result: Any) -> str | None:
        parsed_result = self._parse_json(result)
        additional_data = tool_data.get("additionalData")
        if isinstance(additional_data, dict):
            candidate_id = additional_data.get("subagentComposerId")
            if isinstance(candidate_id, str) and candidate_id.strip():
                return candidate_id.strip()
        if isinstance(parsed_result, dict):
            candidate_id = parsed_result.get("agentId") or parsed_result.get("agent_id")
            if isinstance(candidate_id, str) and candidate_id.strip():
                return candidate_id.strip()
        return None

    def _extract_tool_part(
        self,
        bubble: dict[str, Any],
        timestamp_ms: int,
        *,
        expanding: frozenset[str] = frozenset(),
        subagent_memo: dict[str, dict[str, Any] | None] | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        tool_data = bubble.get("toolFormerData")
        if not isinstance(tool_data, dict):
            return None, None
        name = tool_data.get("name")
        if not isinstance(name, str) or not name:
            return None, None
        if name == "create_plan":
            return None, None

        normalized_input = self._normalize_tool_input(tool_data)
        status = self._extract_tool_status(tool_data)

        result = tool_data.get("result")
        state: dict[str, Any] = {"status": status, "arguments": normalized_input, "output": None}
        if result is not None:
            state["output"] = result
            if isinstance(result, dict):
                error = result.get("error") or result.get("message") or result.get("stderr")
                if error is not None:
                    state["error"] = error

        normalized_name = "subagent" if "agent" in name.lower() or "task" in name.lower() else name
        subagent_id: str | None = None
        subagent_completion: dict[str, Any] | None = None
        if normalized_name == "subagent":
            state["prompt"] = self._extract_subagent_prompt(normalized_input)
            subagent_type = self._extract_subagent_type(normalized_input)
            if subagent_type:
                state["subagent_type"] = subagent_type
            subagent_id = self._extract_subagent_id(tool_data, result)
            if subagent_id:
                subagent_completion = self._build_subagent_completion_message(
                    subagent_id,
                    expanding=expanding,
                    subagent_memo=subagent_memo if subagent_memo is not None else {},
                )
                if subagent_completion is not None and subagent_completion.get("model"):
                    state["model"] = subagent_completion["model"]
                if subagent_completion is not None:
                    subagent_type = subagent_completion.get("subagent_type")
                    if isinstance(subagent_type, str) and subagent_type.strip():
                        state["subagent_type"] = subagent_type.strip()
                state["output"] = None

        tool_part = {
            "type": "tool",
            "tool": normalized_name,
            "callID": tool_data.get("toolCallId") or tool_data.get("callId") or "",
            "title": name,
            "state": state,
            "time_created": timestamp_ms,
        }
        if normalized_name == "subagent" and subagent_id:
            tool_part["subagent_id"] = subagent_id
            state["subagent_id"] = subagent_id
            subagent_type = state.get("subagent_type")
            if isinstance(subagent_type, str) and subagent_type.strip():
                tool_part["subagent_type"] = subagent_type.strip()
        return tool_part, subagent_completion

    def _extract_tool_parent_message_id(self, bubble: dict[str, Any]) -> str | None:
        """Extract parent message/bubble id for tool attachment when available."""
        candidates: list[Any] = []
        candidates.extend(
            [
                bubble.get("parentMessageId"),
                bubble.get("parentBubbleId"),
            ]
        )
        tool_data = bubble.get("toolFormerData")
        if isinstance(tool_data, dict):
            candidates.extend(
                [
                    tool_data.get("parentMessageId"),
                    tool_data.get("parentBubbleId"),
                    tool_data.get("messageId"),
                ]
            )
            additional_data = tool_data.get("additionalData")
            if isinstance(additional_data, dict):
                candidates.extend(
                    [
                        additional_data.get("parentMessageId"),
                        additional_data.get("parentBubbleId"),
                        additional_data.get("messageId"),
                    ]
                )

        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _extract_tokens(self, bubble: dict[str, Any]) -> tuple[int, int]:
        token_count = bubble.get("tokenCount")
        if isinstance(token_count, dict):
            return safe_int(token_count.get("inputTokens")), safe_int(token_count.get("outputTokens"))
        usage = bubble.get("usage")
        if isinstance(usage, dict):
            return safe_int(usage.get("input_tokens")), safe_int(usage.get("output_tokens"))
        cws = bubble.get("contextWindowStatusAtCreation")
        if isinstance(cws, dict) and cws.get("tokensUsed") is not None:
            return safe_int(cws.get("tokensUsed")), 0
        return 0, 0

    def get_session_data(self, session: Session) -> dict[str, Any]:
        """Get Cursor session data as unified dictionary."""
        return cast(
            dict[str, Any],
            self._build_session_data(session, expanding=frozenset(), subagent_memo={}),
        )

    def _build_session_data(
        self,
        session: Session,
        *,
        expanding: frozenset[str],
        subagent_memo: dict[str, dict[str, Any] | None],
    ) -> NormalizedSessionData:
        """Build session data, carrying the subagent-expansion context down the recursion.

        `expanding` 是当前正在展开的 composer id 链，用于挡住 subagentComposerId
        形成的引用环；`subagent_memo` 让同一次顶层调用里多个 tool part 指向同一个
        subagent 时只解析一次。两者都随调用链传递而不是挂在实例上，因为
        get_session_data 会被搜索索引的线程池并发调用。
        """
        composer_id = session.metadata.get("composer_id")
        if not isinstance(composer_id, str) or not composer_id:
            composer_id = session.id
        lower, upper = _key_prefix_bounds(f"bubbleId:{composer_id}:")
        bubble_rows = self._query_global(
            "SELECT key, value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY rowid ASC",
            (lower, upper),
        )

        total_input_tokens = 0
        total_output_tokens = 0
        messages: list[dict[str, Any]] = []
        bubble_message_index: dict[str, int] = {}
        fallback_created_ms = int(session.created_at.timestamp() * 1000)
        active_model_name: str | None = None

        for row in bubble_rows:
            key = str(row["key"])
            bubble_id = key.split(":")[-1]
            bubble = self._parse_json(row["value"])
            if not bubble:
                messages.append(
                    {
                        "id": bubble_id,
                        "role": "assistant",
                        "agent": "cursor",
                        "mode": None,
                        "model": None,
                        "provider": None,
                        "time_created": fallback_created_ms,
                        "time_completed": None,
                        "tokens": {},
                        "cost": 0,
                        "parts": [{"type": "text", "text": "[corrupted message]", "time_created": fallback_created_ms}],
                    }
                )
                continue

            role = "assistant" if bubble.get("type") == 2 else "user"
            timestamp_ms = self._extract_timestamp(bubble, fallback_created_ms)
            model_info = bubble.get("modelInfo")
            model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
            if role == "user" and isinstance(model_name, str) and model_name.strip():
                active_model_name = model_name.strip()
            resolved_model_name = (
                model_name.strip() if isinstance(model_name, str) and model_name.strip() else active_model_name
            )
            in_tokens, out_tokens = self._extract_tokens(bubble)
            total_input_tokens += in_tokens
            total_output_tokens += out_tokens

            text_content = self._extract_text_content(bubble, role)
            tool_data = bubble.get("toolFormerData")
            plan_part = (
                self._build_plan_part(tool_data, timestamp_ms)
                if isinstance(tool_data, dict) and tool_data.get("name") == "create_plan"
                else None
            )
            tool_part, subagent_completion = self._extract_tool_part(
                bubble, timestamp_ms, expanding=expanding, subagent_memo=subagent_memo
            )
            parent_message_id = self._extract_tool_parent_message_id(bubble) if tool_part else None

            if text_content:
                message = {
                    "id": bubble_id,
                    "role": role,
                    "agent": "cursor",
                    "mode": None,
                    "model": resolved_model_name,
                    "provider": None,
                    "time_created": timestamp_ms,
                    "time_completed": None,
                    "tokens": {"input": in_tokens, "output": out_tokens},
                    "cost": 0,
                    "parts": [{"type": "text", "text": text_content, "time_created": timestamp_ms}],
                }
                if plan_part:
                    message["parts"].append(plan_part)
                messages.append(message)
                bubble_message_index[bubble_id] = len(messages) - 1

            if tool_part:
                if parent_message_id and parent_message_id in bubble_message_index:
                    parent_idx = bubble_message_index[parent_message_id]
                    messages[parent_idx]["parts"].append(tool_part)
                else:
                    tool_message = {
                        "id": f"{bubble_id}:tool",
                        "role": "tool",
                        "agent": "cursor",
                        "mode": "tool",
                        "model": resolved_model_name,
                        "provider": None,
                        "time_created": timestamp_ms,
                        "time_completed": None,
                        "tokens": {"input": 0, "output": 0},
                        "cost": 0,
                        "parts": [tool_part],
                    }
                    messages.append(tool_message)

            if plan_part and not text_content:
                messages.append(
                    {
                        "id": bubble_id,
                        "role": "assistant",
                        "agent": "cursor",
                        "mode": None,
                        "model": resolved_model_name,
                        "provider": None,
                        "time_created": timestamp_ms,
                        "time_completed": None,
                        "tokens": {"input": in_tokens, "output": out_tokens},
                        "cost": 0,
                        "parts": [plan_part],
                    }
                )
                continue

            if not text_content and not tool_part:
                continue

            if subagent_completion is not None:
                messages.append(subagent_completion)

        messages = sorted(
            messages,
            key=lambda message: safe_int(message.get("time_created"), fallback_created_ms),
        )

        usage_data = session.metadata.get("usage_data")
        usage_context_tokens = None
        usage_context_limit = None
        usage_context_percent = None
        if isinstance(usage_data, dict):
            usage_context_tokens = usage_data.get("contextTokensUsed")
            usage_context_limit = usage_data.get("contextTokenLimit")
            usage_context_percent = usage_data.get("contextUsagePercent")

        return {
            "id": session.id,
            "title": session.title,
            "slug": None,
            "directory": None,
            "version": None,
            "time_created": int(session.created_at.timestamp() * 1000),
            "time_updated": int(session.updated_at.timestamp() * 1000),
            "summary_files": None,
            "stats": {
                "total_cost": 0,
                "total_input_tokens": total_input_tokens,
                "total_output_tokens": total_output_tokens,
                "message_count": len(messages),
                "context_tokens_used": usage_context_tokens,
                "context_token_limit": usage_context_limit,
                "context_usage_percent": usage_context_percent,
            },
            "metadata": {
                "composer_id": session.metadata.get("composer_id"),
                "request_id": session.metadata.get("request_id"),
                "parent_composer_id": session.metadata.get("parent_composer_id"),
                "subagent_composer_ids": session.metadata.get("subagent_composer_ids"),
            },
            "messages": messages,
        }

    def get_session_head(self, session: Session) -> dict[str, Any]:
        head = super().get_session_head(session)
        composer_id = session.metadata.get("composer_id")
        if not isinstance(composer_id, str) or not composer_id:
            composer_id = session.id

        subtargets = session.metadata.get("subagent_composer_ids")
        if isinstance(subtargets, list):
            head["subtargets"] = [str(item) for item in subtargets if str(item).strip()]

        composer = self._load_composer_by_id(composer_id)
        if isinstance(composer, dict):
            model_config = composer.get("modelConfig")
            if isinstance(model_config, dict):
                model_name = model_config.get("modelName")
                if isinstance(model_name, str) and model_name.strip():
                    head["model"] = model_name.strip()

        lower, upper = _key_prefix_bounds(f"bubbleId:{composer_id}:")
        rows = self._query_global(
            "SELECT value FROM cursorDiskKV WHERE key >= ? AND key < ? ORDER BY key",
            (lower, upper),
        )
        message_count = 0
        for row in rows:
            bubble = self._parse_json(row["value"])
            if not bubble:
                continue
            bubble_type = bubble.get("type")
            if bubble_type in {1, 2}:
                message_count += 1
            if head.get("model"):
                continue
            model_info = bubble.get("modelInfo")
            if isinstance(model_info, dict):
                model_name = model_info.get("modelName")
                if isinstance(model_name, str) and model_name.strip():
                    head["model"] = model_name.strip()

        head["message_count"] = message_count
        return head

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        raise unsupported_capability(
            "raw export is not supported for Cursor sessions",
            capability_gap="Cursor stores session state in SQLite, not as one raw session file",
            details=(f"session id: {session.id}",),
            next_steps=(
                i18n.t(Keys.DIAG_STEP_USE_JSON_OR_PRINT),
                i18n.t(Keys.DIAG_STEP_CURSOR_INSPECT_SQLITE),
            ),
        )


def sys_platform_startswith(prefix: str) -> bool:
    """Small testable wrapper around platform detection."""
    return sys.platform.startswith(prefix)
