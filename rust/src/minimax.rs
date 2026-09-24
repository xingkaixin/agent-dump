use crate::desktop::{Kind, timestamp};
use crate::provider_error::ProviderError;
use crate::session::{Message, Part, Session, SessionData, Stats, TextPart};
use crate::sqlite::rows;
use crate::value::{integer, objects, parse_json, string, text, truthy};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

pub fn search_roots() -> crate::Result<Vec<(&'static str, PathBuf)>> {
    let home = crate::file_sessions::environment_root("HOME", "")?;
    let selected = ["MINIMAX_DATA_DIR", "MAVIS_DATA_DIR"]
        .into_iter()
        .filter_map(|name| Some((name, std::env::var(name).ok()?.trim().to_owned())))
        .find(|(_, value)| !value.is_empty());
    let root = match selected.as_ref().map(|(_, value)| value.as_str()) {
        Some("~") => home,
        Some(value) if value.starts_with("~/") => home.join(&value[2..]),
        Some(value) => PathBuf::from(value),
        None => home.join(".minimax"),
    };
    let label = match selected.as_ref().map(|(name, _)| *name) {
        Some("MINIMAX_DATA_DIR") => "MINIMAX_DATA_DIR/v2/sqlite/runtime-state.sqlite",
        Some("MAVIS_DATA_DIR") => "MAVIS_DATA_DIR/v2/sqlite/runtime-state.sqlite",
        _ => "MiniMax Code ~/.minimax/v2/sqlite/runtime-state.sqlite",
    };
    Ok(vec![(label, root.join("v2/sqlite/runtime-state.sqlite"))])
}

fn validate(connection: &Connection, path: &Path) -> crate::Result<()> {
    for (table, required) in [
        (
            "local_runtime_sessions",
            "session_id columnar_version runtime visibility session_kind archived title workspace_dir parent_session_id created_at_ms updated_at_ms extra_data_json",
        ),
        (
            "local_runtime_message_rows",
            "id session_id msg_id role turn_id source created_at_ms data_json",
        ),
        ("local_runtime_messages", "session_id display_messages_json"),
        ("local_runtime_message_row_migrations", "session_id"),
    ] {
        let columns = rows(connection, &format!("PRAGMA table_info({table})"), &[])?;
        if required
            .split_whitespace()
            .any(|name| !columns.iter().any(|column| column["name"] == name))
        {
            return Err(ProviderError::capability(
                ["This database does not contain the supported MiniMax Code session tables and columns.", "数据库不包含受支持的 MiniMax Code 会话表和字段。"],
                ["Use the current CLI v2/sqlite/runtime-state.sqlite database. Legacy history recovery and desktop data are not supported.", "请使用当前 CLI 的 v2/sqlite/runtime-state.sqlite 数据库，暂不支持旧版历史恢复和桌面端数据。"],
                vec![crate::source_io::path_text(path), table.into()],
            ).into());
        }
    }
    Ok(())
}

pub fn sessions(
    connection: &Connection,
    path: &Path,
    id: Option<&str>,
    cutoff: Option<i64>,
) -> crate::Result<crate::provider::Discovery> {
    validate(connection, path)?;
    let records = rows(
        connection,
        "SELECT s.*, (SELECT COUNT(*) FROM local_runtime_message_rows m WHERE m.session_id = s.session_id) AS message_count, (NOT EXISTS (SELECT 1 FROM local_runtime_message_row_migrations r WHERE r.session_id = s.session_id) AND EXISTS (SELECT 1 FROM local_runtime_messages l WHERE l.session_id = s.session_id AND trim(l.display_messages_json) <> '[]')) AS legacy_pending FROM local_runtime_sessions s WHERE (? IS NULL OR s.session_id = ?) AND (? IS NULL OR COALESCE(s.created_at_ms, s.updated_at_ms) >= ?) ORDER BY COALESCE(s.created_at_ms, s.updated_at_ms) DESC, s.session_id",
        &[&id, &id, &cutoff, &cutoff],
    )?;
    let mut result = crate::provider::Discovery::available(Vec::new());
    for row in records {
        match session(path, &row) {
            Ok(Some(session)) => result.sessions.push(session),
            Ok(None) => (),
            Err(error) if id.is_none() => result.failures.push(crate::provider::SessionFailure {
                source: string(&row["session_id"]),
                error,
            }),
            Err(error) => return Err(error),
        }
    }
    Ok(result)
}

fn session(path: &Path, row: &Value) -> crate::Result<Option<Session>> {
    if row["columnar_version"] != 3 || truthy(&row["legacy_pending"]) {
        return Err(ProviderError::Message([
            "MiniMax Code session storage is unsupported or its display migration is incomplete. Open the session in a compatible MiniMax Code CLI to complete migration; agent-dump never migrates source data.",
            "MiniMax Code 会话存储版本不受支持，或展示消息尚未完成迁移。请使用兼容的 MiniMax Code CLI 打开会话完成迁移；agent-dump 不会迁移源数据。",
        ]).into());
    }
    if row["runtime"] != "pi-agent"
        || row["visibility"] == "hidden"
        || !matches!(
            text(&row["session_kind"]),
            "conversation" | "task" | "unknown"
        )
    {
        return Ok(None);
    }
    let id = string(&row["session_id"]);
    let extra = crate::sqlite::json_cell(&row["extra_data_json"])?;
    if !extra.is_object() {
        return Err(
            ProviderError::invalid(format!("Invalid MiniMax Code session metadata: {id}")).into(),
        );
    }
    let created = if row["created_at_ms"].is_null() {
        &row["updated_at_ms"]
    } else {
        &row["created_at_ms"]
    };
    let created = timestamp(created)
        .ok_or_else(|| format!("Invalid MiniMax Code session timestamp: {id}"))?;
    let updated = timestamp(&row["updated_at_ms"])
        .ok_or_else(|| format!("Invalid MiniMax Code session timestamp: {id}"))?;
    let directory = text(&row["workspace_dir"]);
    let title = crate::title::normalize_title(text(&row["title"]))
        .or_else(|| crate::title::basename(directory))
        .or_else(|| crate::title::normalize_title(&id))
        .unwrap_or_else(|| "Untitled Session".into());
    let mut session = Session::new(id, title, path.to_owned(), created, updated);
    session.directory = directory.into();
    session.model = text(&extra["effectiveModel"]).trim().into();
    session.message_count = row["message_count"].as_u64().map(|v| v as usize);
    session.source_metadata = row.clone();
    session.source_metadata["model"] = extra["effectiveModel"].clone();
    Ok(Some(session))
}

pub fn read(connection: &Connection, session: &Session) -> crate::Result<SessionData> {
    let current = sessions(connection, &session.source_path, Some(&session.id), None)?
        .sessions
        .into_iter()
        .next()
        .ok_or_else(|| {
            Kind::MiniMax.missing_source(&session.source_path, Some(&session.id), Vec::new())
        })?;
    let messages = rows(connection, "SELECT msg_id, role, turn_id, source, created_at_ms, data_json FROM local_runtime_message_rows WHERE session_id = ? ORDER BY id", &[&session.id])?.iter().map(decode).collect::<crate::Result<Vec<_>>>()?;
    let stats = Stats {
        message_count: messages.len(),
        ..Default::default()
    };
    let mut payload = current.payload(messages, stats);
    payload.directory = current.source_metadata["workspace_dir"].clone();
    payload
        .extra
        .insert("model".into(), current.source_metadata["model"].clone());
    payload.extra.insert(
        "parent_session_id".into(),
        current.source_metadata["parent_session_id"].clone(),
    );
    Ok(payload)
}

fn decode(row: &Value) -> crate::Result<Message> {
    let id = string(&row["msg_id"]);
    let data = crate::sqlite::json_cell(&row["data_json"])?;
    if !data.is_object() || data["msg_id"] != row["msg_id"] {
        return Err(
            ProviderError::invalid(format!("Invalid MiniMax Code display message: {id}")).into(),
        );
    }
    let time = integer(&row["created_at_ms"]);
    let kind = text(&data["kind"]);
    let role = if !kind.is_empty() {
        if kind.starts_with("compaction") {
            "compaction"
        } else {
            "custom"
        }
    } else if data["msg_type"] == 3 {
        "system"
    } else if !matches!(data["msg_type"].as_i64(), None | Some(1 | 2))
        || (!data["msg_type"].is_null() && !data["msg_type"].is_number())
    {
        "unknown"
    } else {
        text(data.get("role").unwrap_or(&row["role"]))
    };
    let role = if role == "user"
        && text(&data["msg_content"])
            .trim_start()
            .starts_with("<permission-response>")
    {
        "custom"
    } else {
        role
    };
    let mut message = Message::new(string(&row["msg_id"]), role, time, Vec::new());
    for field in ["turn_id", "source"] {
        message.extra.insert(field.into(), row[field].clone());
    }
    for field in ["kind", "finish_reason"] {
        message.extra.insert(field.into(), data[field].clone());
    }
    let empty = json!([]);
    message.extra.insert(
        "attachments".into(),
        objects(data.get("attachments").unwrap_or(&empty))
            .map_err(|_| ProviderError::invalid(format!("Invalid MiniMax Code attachments: {id}")))?
            .iter()
            .map(attachment)
            .collect(),
    );
    for (source, target) in [
        ("input_tokens", "input"),
        ("output_tokens", "output"),
        ("total_tokens", "total"),
    ] {
        if nonnegative_integer(&data["usage"][source]) {
            message
                .tokens
                .insert(target.into(), data["usage"][source].clone());
        }
    }
    let mut cache = serde_json::Map::new();
    for (source, target) in [("cache_read", "read"), ("cache_write", "write")] {
        if nonnegative_integer(&data["usage"][source]) {
            cache.insert(target.into(), data["usage"][source].clone());
        }
    }
    if !cache.is_empty() {
        message.tokens.insert("cache".into(), cache.into());
    }
    if !matches!(message.role.as_str(), "user" | "assistant" | "tool") {
        message
            .parts
            .push(Part::event("minimax_event".into(), data, time));
        return Ok(message);
    }
    for field in ["thinking_content", "msg_content"] {
        match &data[field] {
            Value::String(value) if !value.is_empty() => {
                message.parts.push(if field == "thinking_content" {
                    Part::Reasoning(TextPart {
                        text: value.clone(),
                        time_created: time,
                    })
                } else {
                    Part::text(value.clone(), time)
                })
            }
            Value::Null | Value::String(_) => (),
            _ => {
                return Err(
                    ProviderError::invalid(format!("Invalid MiniMax Code {field}: {id}")).into(),
                );
            }
        }
    }
    for tool in objects(data.get("tool_calls").unwrap_or(&empty))
        .map_err(|_| ProviderError::invalid(format!("Invalid MiniMax Code tool_calls: {id}")))?
    {
        let name = tool["tool_name"].as_str().ok_or_else(|| {
            ProviderError::invalid(format!("Invalid MiniMax Code tool call: {id}"))
        })?;
        let id = tool["tool_call_id"].as_str().ok_or_else(|| {
            ProviderError::invalid(format!("Invalid MiniMax Code tool call: {id}"))
        })?;
        let status = match integer(&tool["tool_call_status"]) {
            1 => "running",
            2 => "completed",
            3 => "error",
            4 | 5 => "pending",
            _ => "unknown",
        };
        message.parts.push(Part::tool(name, id, json!({"status":status, "input":parse_json(tool.get("tool_call_args").unwrap_or(&tool["tool_call_args_delta"])), "output":parse_json(&tool["tool_call_result_data"]), "duration_ms":tool["tool_call_duration_ms"]}), time));
    }
    Ok(message)
}

fn attachment(item: &Value) -> Value {
    let first = |values: &[&Value]| {
        values
            .iter()
            .find(|v| truthy(v))
            .copied()
            .unwrap_or(values[values.len() - 1])
            .clone()
    };
    json!({"name":first(&[&item["meta"]["fileName"], &item["file_name"], &item["fileName"]]), "path":first(&[&item["local"]["filePath"], &item["file_path"], &item["filePath"]]), "mime_type":first(&[&item["meta"]["mimeType"], &item["mime_type"], &item["mimeType"]]), "type":first(&[&item["meta"]["attachmentType"], &item["type"]]), "size":item["meta"]["sizeBytes"], "url":item["cloud"]["url"], "asset_id":first(&[&item["local"]["assetId"], &item["asset_id"], &item["assetId"]])})
}

fn nonnegative_integer(value: &Value) -> bool {
    value
        .as_number()
        .is_some_and(|number| !number.as_str().contains(['-', '.', 'e', 'E']))
}
