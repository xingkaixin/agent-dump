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
        rows = self._get_bubble_rows(composer_id)
        for row in rows:
            bubble = self._parse_json(row["value"])
            if not bubble:
                continue
            request_id = bubble.get("requestId")
            if isinstance(request_id, str) and request_id.strip():
                return request_id.strip()
        return None

    def _get_bubble_rows(self, composer_id: str) -> list[sqlite3.Row]:
        return self._query_global(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE ? ORDER BY key",
            (f"bubbleId:{composer_id}:%",),
        )

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

    def _augment_session_metadata_from_bubbles(self, metadata: dict[str, Any], bubble_rows: list[sqlite3.Row]) -> None:
        message_count = 0
        model = metadata.get("model")
        for row in bubble_rows:
            bubble = self._parse_json(row["value"])
            if not bubble:
                continue
            bubble_type = bubble.get("type")
            if bubble_type in {1, 2}:
                message_count += 1

            if model is None:
                model_info = bubble.get("modelInfo")
                model_name = model_info.get("modelName") if isinstance(model_info, dict) else None
                if isinstance(model_name, str) and model_name.strip():
                    model = model_name.strip()

        metadata["message_count"] = message_count
        metadata["model"] = model

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
            bubble_rows = self._get_bubble_rows(composer_id)
            request_id = self._extract_request_id_from_bubbles(composer_id) or composer_id
            metadata = self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id)
            self._augment_session_metadata_from_bubbles(metadata, bubble_rows)

            sessions.append(
                Session(
                    id=request_id,
                    title=self._extract_title(composer, composer_id),
                    created_at=created_at,
                    updated_at=updated_at,
                    source_path=self.global_db_path,
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
        created_raw = composer.get("createdAt")
        created_at = self._to_datetime_utc(created_raw)
        updated_raw = composer.get("updatedAt") or composer.get("lastUpdatedAt") or composer.get("lastSendTime")
        updated_at = self._to_datetime_utc(updated_raw if updated_raw is not None else created_raw)
        metadata = self._build_session_metadata(composer, composer_id=composer_id, request_id=request_id)
        self._augment_session_metadata_from_bubbles(metadata, self._get_bubble_rows(composer_id))
        return Session(
            id=request_id,
            title=self._extract_title(composer, composer_id),
            created_at=created_at,
            updated_at=updated_at,
            source_path=self.global_db_path if self.global_db_path else Path(""),
            metadata=metadata,
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
                                "time_created": int(item.get("time_created") or timestamp_ms),
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

    def _extract_subagent_model(self, composer: dict[str, Any], child_data: dict[str, Any]) -> str | None:
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

    def _build_subagent_completion_message(self, composer_id: str) -> dict[str, Any] | None:
        composer = self._load_composer_by_id(composer_id)
        if not composer:
            return None
        child_session = self._build_session_from_composer(
            composer_id=composer_id,
            request_id=composer_id,
            composer=composer,
        )
        child_data = self.get_session_data(child_session)
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
                part_time_created = int(part.get("time_created") or message.get("time_created") or 0)
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
        self, bubble: dict[str, Any], timestamp_ms: int
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
                subagent_completion = self._build_subagent_completion_message(subagent_id)
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
            tool_part, subagent_completion = self._extract_tool_part(bubble, timestamp_ms)
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
