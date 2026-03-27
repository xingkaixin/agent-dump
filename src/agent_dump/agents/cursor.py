"""
Cursor agent handler
"""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from agent_dump.agents.base import BaseAgent, Session


class CursorAgent(BaseAgent):
    """Handler for Cursor sessions stored in SQLite."""

    def __init__(self):
        super().__init__("cursor", "Cursor")
        self.global_db_path: Path | None = None
        self.workspace_root: Path | None = None

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

    def _find_workspace_root(self) -> Path:
        env_path = os.environ.get("CURSOR_DATA_PATH")
        if env_path:
            return Path(env_path).expanduser()
        return self._default_cursor_user_root() / "workspaceStorage"

    def _find_global_db_path(self) -> Path:
        return self._default_cursor_user_root() / "globalStorage" / "state.vscdb"

    def is_available(self) -> bool:
        """Check whether Cursor global/workspace databases are available."""
        self.workspace_root = self._find_workspace_root()
        self.global_db_path = self._find_global_db_path()
        return bool(self.global_db_path.exists() and self.workspace_root.exists())

    def scan(self) -> list[Session]:
        """Scan for all available Cursor sessions."""
        if not self.is_available():
            return []
        return self.get_sessions(days=3650)

    def _query_global(self, sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        if not self.global_db_path:
            return []
        conn = sqlite3.connect(self.global_db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()

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

    def _extract_request_id_from_bubbles(self, composer_id: str) -> str | None:
        rows = self._query_global(
            "SELECT value FROM cursorDiskKV WHERE key LIKE ? ORDER BY key",
            (f"bubbleId:{composer_id}:%",),
        )
        for row in rows:
            bubble = self._parse_json(row["value"])
            if not bubble:
                continue
            request_id = bubble.get("requestId")
            if isinstance(request_id, str) and request_id.strip():
                return request_id.strip()
        return None

    def _extract_title(self, composer: dict[str, Any], composer_id: str) -> str:
        name = composer.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        title = composer.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
        return f"Cursor Session {composer_id[:8]}"

    def _to_datetime_utc(self, value: Any) -> datetime:
        if isinstance(value, str):
            if "T" in value:
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
                except ValueError:
                    pass
            try:
                value = float(value)
            except ValueError:
                return datetime.now(timezone.utc)
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return datetime.now(timezone.utc)

    def _build_session_metadata(self, composer: dict[str, Any], *, composer_id: str, request_id: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "composer_id": composer_id,
            "request_id": request_id,
            "parent_composer_id": None,
            "subagent_composer_ids": [],
            "usage_data": composer.get("usageData"),
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

    def get_sessions(self, days: int = 7) -> list[Session]:
        """Get Cursor sessions from the last N days."""
        if (not self.global_db_path or not self.workspace_root) and not self.is_available():
            return []
        if not self.global_db_path:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = self._query_global(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%' ORDER BY rowid DESC",
            (),
        )
        sessions: list[Session] = []
        for row in rows:
            key = str(row["key"])
            composer_id = key.split(":", 1)[1]
            composer = self._parse_json(row["value"])
            if not composer:
                continue

            created_raw = composer.get("createdAt")
            created_at = self._to_datetime_utc(created_raw)
            if created_at < cutoff:
                continue

            updated_raw = composer.get("updatedAt") or composer.get("lastUpdatedAt") or composer.get("lastSendTime")
            updated_at = self._to_datetime_utc(updated_raw if updated_raw is not None else created_raw)
            request_id = self._extract_request_id_from_bubbles(composer_id) or composer_id

            sessions.append(
                Session(
                    id=request_id,
                    title=self._extract_title(composer, composer_id),
                    created_at=created_at,
                    updated_at=updated_at,
                    source_path=self.global_db_path,
                    metadata=self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id),
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
        created_raw = composer.get("createdAt")
        created_at = self._to_datetime_utc(created_raw)
        updated_raw = composer.get("updatedAt") or composer.get("lastUpdatedAt") or composer.get("lastSendTime")
        updated_at = self._to_datetime_utc(updated_raw if updated_raw is not None else created_raw)
        return Session(
            id=request_id,
            title=self._extract_title(composer, composer_id),
            created_at=created_at,
            updated_at=updated_at,
            source_path=self.global_db_path if self.global_db_path else Path(""),
            metadata=self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id),
        )

    def find_session_by_request_id(self, request_id: str) -> Session | None:
        """Resolve any bubble-level requestId to its owning composer session."""
        if not self.global_db_path and not self.is_available():
            return None
        rows = self._query_global(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%' AND value LIKE ? ORDER BY rowid DESC",
            (f"%{request_id}%",),
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
            try:
                return int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                pass
        timing = bubble.get("timingInfo")
        if isinstance(timing, dict):
            for key in ("clientRpcSendTime", "clientSettleTime", "clientEndTime"):
                value = timing.get(key)
                if isinstance(value, (int, float)):
                    return int(value)
                if isinstance(value, str):
                    try:
                        return int(float(value))
                    except ValueError:
                        continue
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

    def _extract_tool_part(self, bubble: dict[str, Any], timestamp_ms: int) -> dict[str, Any] | None:
        tool_data = bubble.get("toolFormerData")
        if not isinstance(tool_data, dict):
            return None
        name = tool_data.get("name")
        if not isinstance(name, str) or not name:
            return None

        raw_input = tool_data.get("params")
        if raw_input is None:
            raw_input = tool_data.get("rawArgs")
        normalized_input: Any = raw_input
        if isinstance(raw_input, str):
            try:
                normalized_input = json.loads(raw_input)
            except json.JSONDecodeError:
                normalized_input = {"_raw": raw_input}

        add = tool_data.get("additionalData")
        status = add.get("status") if isinstance(add, dict) else None
        if not status:
            status = tool_data.get("status")

        result = tool_data.get("result")
        state: dict[str, Any] = {"status": status, "arguments": normalized_input, "output": None}
        if result is not None:
            state["output"] = result
            if isinstance(result, dict):
                error = result.get("error") or result.get("message") or result.get("stderr")
                if error is not None:
                    state["error"] = error

        return {
            "type": "tool",
            "tool": "subagent" if "agent" in name.lower() or "task" in name.lower() else name,
            "callID": tool_data.get("toolCallId") or tool_data.get("callId") or "",
            "title": name,
            "state": state,
            "time_created": timestamp_ms,
        }

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
            return int(token_count.get("inputTokens") or 0), int(token_count.get("outputTokens") or 0)
        usage = bubble.get("usage")
        if isinstance(usage, dict):
            return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
        cws = bubble.get("contextWindowStatusAtCreation")
        if isinstance(cws, dict) and cws.get("tokensUsed") is not None:
            return int(cws.get("tokensUsed") or 0), 0
        return 0, 0

    def get_session_data(self, session: Session) -> dict:
        """Get Cursor session data as unified dictionary."""
        composer_id = session.metadata.get("composer_id")
        if not isinstance(composer_id, str) or not composer_id:
            composer_id = session.id
        bubble_rows = self._query_global(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? ORDER BY rowid ASC",
            (f"bubbleId:{composer_id}:%",),
        )

        total_input_tokens = 0
        total_output_tokens = 0
        messages: list[dict[str, Any]] = []
        bubble_message_index: dict[str, int] = {}
        fallback_created_ms = int(session.created_at.timestamp() * 1000)

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
            in_tokens, out_tokens = self._extract_tokens(bubble)
            total_input_tokens += in_tokens
            total_output_tokens += out_tokens

            text_content = self._extract_text_content(bubble, role)
            tool_part = self._extract_tool_part(bubble, timestamp_ms)
            parent_message_id = self._extract_tool_parent_message_id(bubble) if tool_part else None

            if text_content:
                message = {
                    "id": bubble_id,
                    "role": role,
                    "agent": "cursor",
                    "mode": None,
                    "model": model_name,
                    "provider": None,
                    "time_created": timestamp_ms,
                    "time_completed": None,
                    "tokens": {"input": in_tokens, "output": out_tokens},
                    "cost": 0,
                    "parts": [{"type": "text", "text": text_content, "time_created": timestamp_ms}],
                }
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
                        "model": model_name,
                        "provider": None,
                        "time_created": timestamp_ms,
                        "time_completed": None,
                        "tokens": {"input": 0, "output": 0},
                        "cost": 0,
                        "parts": [tool_part],
                    }
                    messages.append(tool_message)

            if not text_content and not tool_part:
                messages.append(
                    {
                        "id": bubble_id,
                        "role": role,
                        "agent": "cursor",
                        "mode": None,
                        "model": model_name,
                        "provider": None,
                        "time_created": timestamp_ms,
                        "time_completed": None,
                        "tokens": {"input": in_tokens, "output": out_tokens},
                        "cost": 0,
                        "parts": [{"type": "text", "text": "[empty message]", "time_created": timestamp_ms}],
                    }
                )

        messages = sorted(messages, key=lambda message: int(message.get("time_created") or fallback_created_ms))

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

    def export_session(self, session: Session, output_dir: Path) -> Path:
        """Export a single Cursor session to JSON."""
        session_data = self.get_session_data(session)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{session.id}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
        return output_path

    def export_raw_session(self, session: Session, output_dir: Path) -> Path:
        raise NotImplementedError("Raw export is not supported for Cursor sessions")


def sys_platform_startswith(prefix: str) -> bool:
    """Small testable wrapper around platform detection."""
    return sys.platform.startswith(prefix)
