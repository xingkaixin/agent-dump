use crate::compat::value::{
    integer, objects, parse_json, string, text, truthy,
};
use crate::providers::desktop::{Kind, timestamp};
use crate::providers::error::ProviderError;
use crate::providers::sqlite::connection::has_table;
use crate::providers::sqlite::connection::rows;
use crate::session::{Message, Part, Session, SessionData, Stats, TextPart};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};

const DATABASE: &str = "v2/sqlite/runtime-state.sqlite";
const MESSAGES: &str = "SELECT msg_id, role, turn_id, source, created_at_ms, data_json FROM local_runtime_message_rows WHERE session_id = ? ORDER BY id";

pub fn search_roots() -> crate::Result<Vec<(&'static str, PathBuf)>> {
    for (variable, label) in [
        (
            "MINIMAX_DATA_DIR",
            "MINIMAX_DATA_DIR/v2/sqlite/runtime-state.sqlite",
        ),
        (
            "MAVIS_DATA_DIR",
            "MAVIS_DATA_DIR/v2/sqlite/runtime-state.sqlite",
        ),
    ] {
        if let Some(root) = crate::providers::files::environment_path(variable)?
        {
            return Ok(vec![(label, root.join(DATABASE))]);
        }
    }
    let home = crate::providers::files::environment_root("HOME", "")?;
    let primary = home.join(".minimax").join(DATABASE);
    let legacy = home.join(".minimax-code").join(DATABASE);
    Ok(vec![if !primary.exists() && legacy.exists() {
        (
            "MiniMax Code ~/.minimax-code/v2/sqlite/runtime-state.sqlite",
            legacy,
        )
    } else {
        (
            "MiniMax Code ~/.minimax/v2/sqlite/runtime-state.sqlite",
            primary,
        )
    }])
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
        let columns =
            rows(connection, &format!("PRAGMA table_info({table})"), &[])?;
        if required
            .split_whitespace()
            .any(|name| !columns.iter().any(|column| column["name"] == name))
        {
            return Err(ProviderError::capability(
                ["This database does not contain the supported MiniMax Code session tables and columns.", "数据库不包含受支持的 MiniMax Code 会话表和字段。"],
                ["Use the current CLI v2/sqlite/runtime-state.sqlite database. Legacy history recovery and desktop data are not supported.", "请使用当前 CLI 的 v2/sqlite/runtime-state.sqlite 数据库，暂不支持旧版历史恢复和桌面端数据。"],
                vec![crate::storage::source_io::path_text(path), table.into()],
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
) -> crate::Result<crate::providers::contract::Discovery> {
    validate(connection, path)?;
    let usage = if has_table(connection, "local_runtime_token_usage")? {
        "(SELECT MAX(u.ts) FROM local_runtime_token_usage u WHERE u.session_id = s.session_id)"
    } else {
        "NULL"
    };
    let records = rows(
        connection,
        &format!(
            "SELECT s.*, (SELECT COUNT(*) FROM local_runtime_message_rows m WHERE m.session_id = s.session_id) AS message_count, (SELECT MAX(m.created_at_ms) FROM local_runtime_message_rows m WHERE m.session_id = s.session_id) AS message_activity, {usage} AS usage_activity, (NOT EXISTS (SELECT 1 FROM local_runtime_message_row_migrations r WHERE r.session_id = s.session_id) AND EXISTS (SELECT 1 FROM local_runtime_messages l WHERE l.session_id = s.session_id AND trim(l.display_messages_json) <> '[]')) AS legacy_pending FROM local_runtime_sessions s WHERE (? IS NULL OR s.session_id = ?) AND (? IS NULL OR COALESCE(s.created_at_ms, s.updated_at_ms) >= ?) ORDER BY COALESCE(s.created_at_ms, s.updated_at_ms) DESC, s.session_id"
        ),
        &[&id, &id, &cutoff, &cutoff],
    )?;
    let mut result =
        crate::providers::contract::Discovery::available(Vec::new());
    for row in records {
        match session(connection, path, &row) {
            Ok(Some(session)) => result.sessions.push(session),
            Ok(None) => (),
            Err(error) if id.is_none() => result.failures.push(
                crate::providers::contract::SessionFailure {
                    source: string(&row["session_id"]),
                    error,
                },
            ),
            Err(error) => return Err(error),
        }
    }
    Ok(result)
}

fn session(
    connection: &Connection,
    path: &Path,
    row: &Value,
) -> crate::Result<Option<Session>> {
    if (row["visibility"] == "hidden"
        && text(&row["parent_session_id"]).is_empty())
        || matches!(text(&row["session_kind"]), "peek" | "cron" | "channel")
    {
        return Ok(None);
    }
    if row["columnar_version"] != 3 || truthy(&row["legacy_pending"]) {
        return Err(ProviderError::Message([
            "MiniMax Code session storage is unsupported or its display migration is incomplete. Open the session in a compatible MiniMax Code CLI to complete migration; agent-dump never migrates source data.",
            "MiniMax Code 会话存储版本不受支持，或展示消息尚未完成迁移。请使用兼容的 MiniMax Code CLI 打开会话完成迁移；agent-dump 不会迁移源数据。",
        ]).into());
    }
    if integer(&row["message_count"]) == 0 {
        return Ok(None);
    }
    let id = string(&row["session_id"]);
    let extra = crate::providers::sqlite::connection::json_cell(
        &row["extra_data_json"],
    )?;
    if !extra.is_object() {
        return Err(ProviderError::invalid(format!(
            "Invalid MiniMax Code session metadata: {id}"
        ))
        .into());
    }
    let created = if row["created_at_ms"].is_null() {
        &row["updated_at_ms"]
    } else {
        &row["created_at_ms"]
    };
    let created = timestamp(created).ok_or_else(|| {
        format!("Invalid MiniMax Code session timestamp: {id}")
    })?;
    let updated = timestamp(&row["updated_at_ms"]).ok_or_else(|| {
        format!("Invalid MiniMax Code session timestamp: {id}")
    })?;
    let updated = [&row["message_activity"], &row["usage_activity"]]
        .into_iter()
        .filter_map(timestamp)
        .fold(updated, Ord::max);
    let directory = text(&row["workspace_dir"]);
    let title = title(text(&row["title"]))
        .map_or_else(|| prompt(connection, &id), |title| Ok(Some(title)))?
        .or_else(|| crate::providers::title::basename(directory))
        .or_else(|| crate::providers::title::normalize_title(&id))
        .unwrap_or_else(|| "Untitled Session".into());
    let mut session =
        Session::new(id, title, path.to_owned(), created, updated);
    session.directory = directory.into();
    session.model = text(&extra["effectiveModel"]).trim().into();
    session.message_count = row["message_count"]
        .as_u64()
        .and_then(|v| usize::try_from(v).ok());
    session.source_metadata = row.clone();
    session.source_metadata["model"] = extra["effectiveModel"].clone();
    Ok(Some(session))
}

fn title(value: &str) -> Option<String> {
    crate::providers::text::clean(value)
        .lines()
        .find_map(crate::providers::title::normalize_title)
}

fn prompt(connection: &Connection, id: &str) -> crate::Result<Option<String>> {
    Ok(rows(connection, MESSAGES, &[&id])?
        .iter()
        .filter_map(|row| decode(row).ok())
        .filter(|message| message.role == "user" && !automated(message))
        .find_map(|message| {
            message.parts.iter().find_map(|part| match part {
                Part::Text(part) => title(&part.text),
                _ => None,
            })
        }))
}

fn automated(message: &Message) -> bool {
    let field = |name| message.extra.get(name).map_or("", text);
    !field("kind").is_empty()
        || matches!(
            field("source"),
            "cron" | "thread-goal" | "team" | "background-task" | "system"
        )
}

pub fn read(
    connection: &Connection,
    session: &Session,
) -> crate::Result<SessionData> {
    let current =
        sessions(connection, &session.source_path, Some(&session.id), None)?
            .sessions
            .into_iter()
            .next()
            .ok_or_else(|| {
                Kind::MiniMax.missing_source(
                    &session.source_path,
                    Some(&session.id),
                    Vec::new(),
                )
            })?;
    let mut messages = rows(connection, MESSAGES, &[&session.id])?
        .iter()
        .map(decode)
        .collect::<crate::Result<Vec<_>>>()?;
    let usage = if has_table(connection, "local_runtime_token_usage")? {
        rows(
            connection,
            "SELECT * FROM local_runtime_token_usage WHERE session_id = ? ORDER BY id",
            &[&session.id],
        )?
    } else {
        Vec::new()
    };
    let stats = attach(&mut messages, &usage);
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

#[derive(Default)]
struct Usage {
    tokens: [i64; 5],
    cost: f64,
}

impl Usage {
    fn add(&mut self, row: &Value) {
        for (total, field) in self.tokens.iter_mut().zip([
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        ]) {
            *total = total.saturating_add(count(&row[field]));
        }
        self.cost += row["cost_usd"]
            .as_f64()
            .filter(|cost| *cost > 0.0)
            .unwrap_or(0.0);
    }
}

fn attach(messages: &mut [Message], usage: &[Value]) -> Stats {
    let mut answers = HashMap::new();
    for (index, message) in messages.iter().enumerate() {
        if message.role == "assistant"
            && message.mode.is_none()
            && let Some(turn) =
                message.extra.get("turn_id").and_then(Value::as_str)
        {
            answers.insert(turn.to_owned(), index);
        }
    }
    let mut session = Usage::default();
    let mut turns: HashMap<&str, Vec<&Value>> = HashMap::new();
    for row in usage {
        session.add(row);
        if let Some(turn) = row["turn_id"].as_str() {
            turns.entry(turn).or_default().push(row);
        }
    }
    for (turn, rows) in turns {
        let Some(&index) = answers.get(turn) else {
            continue;
        };
        let models: BTreeSet<_> = rows
            .iter()
            .map(|row| row["model"].as_str().filter(|model| !model.is_empty()))
            .collect();
        let [model] = models.into_iter().collect::<Vec<_>>()[..] else {
            continue;
        };
        let mut total = Usage::default();
        for row in rows {
            total.add(row);
        }
        let [input, output, reasoning, read, write] = total.tokens;
        let message = &mut messages[index];
        message.model = model.map(Value::from);
        message.tokens.clone_from(
            json!({"input": input, "output": output, "reasoning": reasoning, "cache": {"read": read, "write": write}})
                .as_object()
                .unwrap(),
        );
        if total.cost > 0.0 {
            message.cost = crate::compat::json::float(total.cost);
        }
    }
    let mut stats = Stats {
        message_count: messages.len(),
        ..Default::default()
    };
    if !usage.is_empty() {
        let tokens = session.tokens;
        stats.total_input_tokens = tokens[0].into();
        stats.total_output_tokens = tokens[1].into();
        stats.total_cost = crate::compat::json::float(session.cost);
        stats.total_tokens =
            Some(tokens.into_iter().fold(0_i64, i64::saturating_add).into());
    }
    stats
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "Token counts are integral; out-of-range values saturate"
)]
fn count(value: &Value) -> i64 {
    value.as_f64().filter(|count| *count > 0.0).unwrap_or(0.0) as i64
}

fn decode(row: &Value) -> crate::Result<Message> {
    let id = string(&row["msg_id"]);
    let data =
        crate::providers::sqlite::connection::json_cell(&row["data_json"])?;
    if !data.is_object() || data["msg_id"] != row["msg_id"] {
        return Err(ProviderError::invalid(format!(
            "Invalid MiniMax Code display message: {id}"
        ))
        .into());
    }
    let time = integer(&row["created_at_ms"]);
    let kind = text(&data["kind"]);
    let role = if data["msg_type"] == 3 {
        "system"
    } else if !matches!(data["msg_type"].as_i64(), None | Some(1 | 2))
        || (!data["msg_type"].is_null() && !data["msg_type"].is_number())
    {
        "unknown"
    } else {
        text(data.get("role").unwrap_or_else(|| &row["role"]))
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
    let mut message =
        Message::new(string(&row["msg_id"]), role, time, Vec::new());
    if !kind.is_empty() {
        message.mode = Some(kind.into());
    }
    for field in ["turn_id", "source"] {
        message.extra.insert(field.into(), row[field].clone());
    }
    for field in ["kind", "finish_reason"] {
        message.extra.insert(field.into(), data[field].clone());
    }
    let empty = json!([]);
    let attachments = objects(data.get("attachments").unwrap_or(&empty))
        .map_err(|_| {
            ProviderError::invalid(format!(
                "Invalid MiniMax Code attachments: {id}"
            ))
        })?;
    let records: Vec<Value> = attachments.iter().map(attachment).collect();
    message
        .extra
        .insert("attachments".into(), records.clone().into());
    if !matches!(message.role.as_str(), "user" | "assistant" | "tool") {
        message
            .parts
            .push(Part::event("minimax_event".into(), data, time));
        return Ok(message);
    }
    if !kind.is_empty() {
        message.parts.push(Part::text(label(kind), time));
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
                });
            }
            Value::Null | Value::String(_) => (),
            _ => {
                return Err(ProviderError::invalid(format!(
                    "Invalid MiniMax Code {field}: {id}"
                ))
                .into());
            }
        }
    }
    for (item, record) in attachments.iter().zip(&records) {
        let name = [
            &record["path"],
            &item["desktop_path"],
            &record["name"],
            &record["asset_id"],
            &record["url"],
        ]
        .into_iter()
        .find_map(|value| value.as_str().filter(|name| !name.is_empty()));
        if let Some(name) = name {
            let mime = record["mime_type"]
                .as_str()
                .filter(|mime| !mime.is_empty())
                .map(|mime| format!(" ({mime})"))
                .unwrap_or_default();
            message
                .parts
                .push(Part::text(format!("Attachment: {name}{mime}"), time));
        }
    }
    let mut children = BTreeSet::new();
    for tool in
        objects(data.get("tool_calls").unwrap_or(&empty)).map_err(|_| {
            ProviderError::invalid(format!(
                "Invalid MiniMax Code tool_calls: {id}"
            ))
        })?
    {
        let Some(name) =
            tool["tool_name"].as_str().filter(|name| !name.is_empty())
        else {
            continue;
        };
        let id = tool["tool_call_id"].as_str().ok_or_else(|| {
            ProviderError::invalid(format!(
                "Invalid MiniMax Code tool call: {id}"
            ))
        })?;
        let output = parse_json(&tool["tool_call_result_data"]);
        let failed = tool["tool_call_status"] == 3
            || output["isError"] == true
            || !output["error"].is_null();
        let status = match integer(&tool["tool_call_status"]) {
            _ if failed => "error",
            1 => "running",
            2 => "completed",
            4 | 5 => "pending",
            _ => "unknown",
        };
        if name == "task" || name.starts_with("task_") {
            let details = &output["details"];
            if let Some(child) = details["sub_session_id"]
                .as_str()
                .or_else(|| details["session_id"].as_str())
            {
                children.insert(child.to_owned());
            }
        }
        let mut state = json!({"status":status, "input":parse_json(tool.get("tool_call_args").unwrap_or_else(|| &tool["tool_call_args_delta"])), "output":output, "duration_ms":tool["tool_call_duration_ms"]});
        if failed {
            state["error"] = [&output["error"], &output["text"]]
                .into_iter()
                .find(|value| !value.is_null())
                .unwrap_or(&output)
                .clone();
        }
        message.parts.push(Part::tool(name, id, state, time));
    }
    if let Some(error) =
        data["error"].as_str().filter(|error| !error.is_empty())
    {
        message.parts.push(Part::text(error.into(), time));
    }
    if children.len() == 1 {
        message.subagent_id = children.pop_first();
    }
    Ok(message)
}

fn label(kind: &str) -> String {
    match kind {
        "compaction_start" => "Context compaction started",
        "compaction" => "Context compacted",
        "compaction_failed" => "Context compaction failed",
        "review_start" => "Review started",
        "review_result" => "Review result",
        "review_failed" => "Review failed",
        "review_aborted" => "Review aborted",
        "review_interrupted" => "Review interrupted",
        _ => return format!("Event: {kind}"),
    }
    .into()
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
