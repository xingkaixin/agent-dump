use crate::compat::value::{integer, objects, string, text, truthy};
use crate::providers::desktop::{Kind, has_tables, timestamp};
use crate::providers::error::ProviderError;
use crate::providers::sqlite::connection::rows;
use crate::session::timestamp::Timestamp;
use crate::session::{
    ImagePart, Message, Part, Session, SessionData, Stats, TextPart,
};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

pub fn search_roots() -> crate::Result<Vec<(&'static str, PathBuf)>> {
    for variable in
        ["CHERRYSTUDIO_USER_DATA_DIR", "CHERRY_STUDIO_USER_DATA_DIR"]
    {
        if let Some(root) = crate::providers::files::environment_path(variable)?
        {
            return Ok(vec![(
                "Cherry Studio userData",
                root.join("Data/cherrystudio.sqlite"),
            )]);
        }
    }
    let boot = crate::providers::files::environment_root("HOME", "")?
        .join(".cherrystudio/boot-config.json");
    let default = crate::providers::desktop::app_data("CherryStudio")?
        .join("Data/cherrystudio.sqlite");
    storage_roots(&boot, default)
}

pub fn storage_roots(
    boot: &Path,
    default: PathBuf,
) -> crate::Result<Vec<(&'static str, PathBuf)>> {
    let mut roots = Vec::new();
    if boot.is_file() {
        let config = crate::compat::json::from_slice(
            &crate::storage::source_io::read(boot)?,
        )?;
        let object = config
            .as_object()
            .ok_or_else(|| attribute_error(&config, "get"))?;
        if let Some(paths) = object.get("app.user_data_path") {
            let paths = paths
                .as_object()
                .ok_or_else(|| attribute_error(paths, "values"))?;
            for value in paths.values().filter_map(Value::as_str) {
                if Path::new(value).is_absolute() {
                    roots.push(PathBuf::from(value));
                }
            }
        }
    }
    let mut result = Vec::new();
    for path in roots
        .into_iter()
        .map(|p| p.join("Data/cherrystudio.sqlite"))
        .chain(std::iter::once(default))
    {
        if !result.iter().any(|(_, existing)| existing == &path) {
            result.push(("Cherry Studio userData", path));
        }
    }
    Ok(result)
}

fn attribute_error(value: &Value, attribute: &str) -> ProviderError {
    ProviderError::Cause {
        kind: "AttributeError",
        message: format!(
            "'{}' object has no attribute '{attribute}'",
            crate::compat::value::type_name(value)
        ),
    }
}

fn records(
    connection: &Connection,
    path: &Path,
    id: Option<&str>,
    cutoff: Option<i64>,
) -> crate::Result<Vec<Value>> {
    if !has_tables(
        connection,
        &[
            "topic",
            "message",
            "agent_session",
            "agent_session_message",
            "agent_workspace",
        ],
    )? {
        return Err(ProviderError::capability(
            ["This database does not contain the supported Cherry Studio session tables.", "数据库不包含受支持的 Cherry Studio 会话表。"],
            ["Use the Cherry Studio 2.x Data/cherrystudio.sqlite database. Legacy IndexedDB data is not supported.", "请使用 Cherry Studio 2.x 的 Data/cherrystudio.sqlite 数据库，暂不支持旧版 IndexedDB 数据。"],
            vec![crate::storage::source_io::path_text(path)],
        ).into());
    }
    let filter = if has_column(connection, "agent_session", "deleted_at")? {
        "WHERE s.deleted_at IS NULL"
    } else {
        ""
    };
    let activity = |table, column| {
        Ok::<_, crate::Error>(
            if has_column(connection, table, "last_activity_at")? {
                column
            } else {
                "NULL"
            },
        )
    };
    let topic = activity("topic", "last_activity_at")?;
    let session = activity("agent_session", "s.last_activity_at")?;
    rows(
        connection,
        &format!(
            "SELECT * FROM (SELECT 'topic-' || id AS session_id, 'topic' AS kind, id, name, created_at, updated_at, {topic} AS last_activity_at, active_node_id, NULL AS directory FROM topic WHERE deleted_at IS NULL UNION ALL SELECT 'session-' || s.id, 'session', s.id, s.name, s.created_at, s.updated_at, {session}, NULL, w.path FROM agent_session s LEFT JOIN agent_workspace w ON w.id = s.workspace_id {filter}) WHERE (? IS NULL OR session_id = ?) AND (? IS NULL OR created_at >= ?) ORDER BY created_at DESC, session_id"
        ),
        &[&id, &id, &cutoff, &cutoff],
    )
}

fn has_column(
    connection: &Connection,
    table: &str,
    column: &str,
) -> crate::Result<bool> {
    Ok(
        rows(connection, &format!("PRAGMA table_info({table})"), &[])?
            .iter()
            .any(|row| row["name"] == column),
    )
}

fn updated(row: &Value) -> &Value {
    if row["last_activity_at"].is_null() {
        &row["updated_at"]
    } else {
        &row["last_activity_at"]
    }
}

fn title(row: &Value, messages: &[Message]) -> String {
    let first = messages
        .iter()
        .filter(|message| message.role == "user")
        .flat_map(|message| &message.parts)
        .find_map(|part| match part {
            Part::Text(part) => Some(part.text.as_str()),
            _ => None,
        });
    [text(&row["name"]), first.unwrap_or_default()]
        .into_iter()
        .find_map(|candidate| {
            crate::providers::text::clean(candidate)
                .lines()
                .find_map(crate::providers::title::normalize_title)
        })
        .unwrap_or_else(|| "Cherry Studio".into())
}

pub fn sessions(
    connection: &Connection,
    path: &Path,
    id: Option<&str>,
    cutoff: Option<i64>,
) -> crate::Result<crate::providers::contract::Discovery> {
    let mut result =
        crate::providers::contract::Discovery::available(Vec::new());
    for row in records(connection, path, id, cutoff)? {
        match session(connection, path, &row) {
            Ok(Some(session)) => result.sessions.push(session),
            Ok(None) => {}
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
    let records = message_rows(connection, row)?;
    let mut model = String::new();
    for message in records.iter().rev().filter(|m| m["role"] == "assistant") {
        let (candidate, _) = message_model(message)?;
        if truthy(&candidate) {
            model = text(&candidate).into();
            break;
        }
    }
    let mut messages = Vec::new();
    let mut count = 0;
    for record in &records {
        match decode(record) {
            Ok(Some(message)) => {
                count += 1;
                messages.push(message);
            }
            Ok(None) => {}
            Err(_) => count += 1,
        }
    }
    if count == 0 {
        return Ok(None);
    }
    let mut session = Session::new(
        string(&row["session_id"]),
        title(row, &messages),
        path.to_owned(),
        timestamp(&row["created_at"]).unwrap_or(Timestamp::UNIX_EPOCH),
        timestamp(updated(row)).unwrap_or(Timestamp::UNIX_EPOCH),
    );
    session.directory = text(&row["directory"]).into();
    session.model = model.trim().into();
    session.message_count = Some(count);
    Ok(Some(session))
}

fn message_rows(
    connection: &Connection,
    session: &Value,
) -> crate::Result<Vec<Value>> {
    let id = text(&session["id"]);
    if session["kind"] == "session" {
        let filter =
            if has_column(connection, "agent_session_message", "deleted_at")? {
                "AND deleted_at IS NULL"
            } else {
                ""
            };
        return rows(
            connection,
            &format!(
                "SELECT * FROM agent_session_message WHERE session_id = ? {filter} ORDER BY created_at, id"
            ),
            &[&id],
        );
    }
    if !truthy(&session["active_node_id"]) {
        return Ok(Vec::new());
    }
    let active = text(&session["active_node_id"]);
    let records = rows(
        connection,
        "WITH RECURSIVE branch(id, parent_id) AS (SELECT id, parent_id FROM message WHERE id = ? AND topic_id = ? AND deleted_at IS NULL UNION SELECT m.id, m.parent_id FROM message m JOIN branch b ON m.id = b.parent_id WHERE m.topic_id = ? AND m.deleted_at IS NULL) SELECT m.* FROM message m JOIN branch b ON m.id = b.id",
        &[&active, &id, &id],
    )?;
    let by_id: HashMap<_, _> =
        records.iter().map(|row| (text(&row["id"]), row)).collect();
    let mut seen = HashSet::new();
    let mut chain = Vec::new();
    let mut node = active;
    while !node.is_empty() {
        if !seen.insert(node) {
            return Err(ProviderError::invalid(format!(
                "Invalid Cherry Studio active branch: {id}"
            ))
            .into());
        }
        let row = *by_id.get(node).ok_or_else(|| {
            ProviderError::invalid(format!(
                "Invalid Cherry Studio active branch: {id}"
            ))
        })?;
        if row["role"] == "root" {
            if !row["parent_id"].is_null() {
                return Err(ProviderError::invalid(format!(
                    "Invalid Cherry Studio root: {id}"
                ))
                .into());
            }
            chain.reverse();
            return Ok(chain);
        }
        chain.push(row.clone());
        node = text(&row["parent_id"]);
    }
    Err(
        ProviderError::invalid(format!("Missing Cherry Studio root: {id}"))
            .into(),
    )
}

pub fn read(
    connection: &Connection,
    session: &Session,
) -> crate::Result<SessionData> {
    let row =
        records(connection, &session.source_path, Some(&session.id), None)?
            .into_iter()
            .next()
            .ok_or_else(|| {
                Kind::Cherry.missing_source(
                    &session.source_path,
                    Some(&session.id),
                    Vec::new(),
                )
            })?;
    let messages = message_rows(connection, &row)?
        .iter()
        .filter_map(|record| decode(record).transpose())
        .collect::<crate::Result<Vec<_>>>()?;
    let mut stats = Stats {
        total_cost: crate::compat::json::float(
            messages
                .iter()
                .filter_map(|message| {
                    crate::compat::json::nonfinite(&message.cost)
                        .or_else(|| message.cost.as_f64())
                })
                .sum(),
        ),
        message_count: messages.len(),
        ..Default::default()
    };
    for message in &messages {
        stats
            .add_tokens(&message.tokens["input"], &message.tokens["output"])?;
    }
    let title = title(&row, &messages);
    let mut data = session.payload(messages, stats);
    data.title = title;
    data.directory = row["directory"].clone();
    data.time_created = integer(&row["created_at"]);
    data.time_updated = integer(updated(&row));
    Ok(data)
}

fn object(value: &Value) -> crate::Result<Value> {
    if value.is_null() {
        return Ok(json!({}));
    }
    let result = if let Some(text) = value.as_str() {
        crate::compat::json::from_str(text)?
    } else {
        value.clone()
    };
    if result.is_object() {
        Ok(result)
    } else {
        Err("Expected a Cherry Studio JSON object".into())
    }
}

fn message_model(row: &Value) -> crate::Result<(Value, Value)> {
    let snapshot = object(&row["message_snapshot"])?;
    let model = object(&snapshot["model"])?;
    if truthy(&model["id"]) {
        return Ok((model["id"].clone(), model["provider"].clone()));
    }
    Ok(match text(&row["model_id"]).split_once("::") {
        Some((provider, model)) => (model.into(), provider.into()),
        None => (
            if text(&row["model_id"]).is_empty() {
                Value::Null
            } else {
                row["model_id"].clone()
            },
            Value::Null,
        ),
    })
}

fn decode(row: &Value) -> crate::Result<Option<Message>> {
    if row["role"] != "user" && row["role"] != "assistant" {
        return Ok(None);
    }
    let (data, stats, model, provider) = (|| -> crate::Result<_> {
        let data = object(&row["data"])?;
        objects(data.get("parts").unwrap_or(&json!([])))?;
        let stats = object(&row["stats"])?;
        let (model, provider) = message_model(row)?;
        Ok((data, stats, model, provider))
    })()
    .map_err(|_| {
        ProviderError::invalid(format!(
            "Invalid Cherry Studio message: {}",
            string(&row["id"])
        ))
    })?;
    let usage = if row["role"] == "assistant" {
        usage(&stats)?
    } else {
        Usage::default()
    };
    let [input, output, read, write] = usage.tokens;
    let time = integer(&row["created_at"]);
    let mut message =
        Message::new(string(&row["id"]), text(&row["role"]), time, Vec::new());
    message.model = model.as_str().map(std::convert::Into::into);
    message.provider = provider.as_str().map(str::to_owned);
    message.tokens.clone_from(json!({"input": input, "output": output, "cache": {"read": read, "write": write}}).as_object().unwrap());
    if let Some(reasoning) = usage.reasoning {
        message.tokens.insert("reasoning".into(), reasoning.into());
    }
    if usage.cost > 0.0 {
        message.cost = crate::compat::json::float(usage.cost);
    }
    message.extra.insert("status".into(), row["status"].clone());
    message.extra.insert(
        "costs".into(),
        stats.get("costs").cloned().unwrap_or(json!([])),
    );
    for part in objects(data.get("parts").unwrap_or(&json!([])))? {
        message.parts.extend(decode_part(part, time)?);
    }
    let used = usage.tokens.iter().any(|&count| count > 0)
        || usage.reasoning.is_some_and(|count| count > 0)
        || usage.cost > 0.0;
    let mut cleaned = vec![message];
    crate::providers::text::clean_messages(&mut cleaned);
    Ok(cleaned
        .pop()
        .filter(|message| !message.parts.is_empty() || used))
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "Token counts are integral; out-of-range values saturate"
)]
fn count(value: &Value) -> i64 {
    value.as_f64().unwrap_or(0.0) as i64
}

#[derive(Default)]
struct Usage {
    tokens: [i64; 4],
    reasoning: Option<i64>,
    cost: f64,
}

fn usage(stats: &Value) -> crate::Result<Usage> {
    let input = object(&stats["inputTokenDetails"])?;
    let output = object(&stats["outputTokenDetails"])?;
    let read = count(&input["cacheReadTokens"]).max(0);
    let write = count(&input["cacheWriteTokens"]).max(0);
    let reasoning = count(&output["reasoningTokens"]).max(0);
    let total = |key: &str, parts: [i64; 2]| {
        if stats[key].is_number() {
            count(&stats[key])
        } else {
            parts[0].saturating_add(parts[1])
        }
    };
    let costs: Vec<&Value> = stats["costs"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|cost| cost.is_object())
        .collect();
    let cost = if costs.iter().all(|cost| cost["currency"] == "USD") {
        costs
            .iter()
            .map(|cost| cost["amount"].as_f64().unwrap_or(0.0).max(0.0))
            .sum()
    } else {
        0.0
    };
    Ok(Usage {
        tokens: [
            total(
                "inputTokens",
                [
                    count(&input["noCacheTokens"]).max(0),
                    read.saturating_add(write),
                ],
            ),
            total(
                "outputTokens",
                [count(&output["textTokens"]).max(0), reasoning],
            ),
            read,
            write,
        ],
        reasoning: output["reasoningTokens"].is_number().then_some(reasoning),
        cost,
    })
}

fn decode_part(part: &Value, time: i64) -> crate::Result<Option<Part>> {
    let kind = part
        .get("type")
        .map_or(Some("unknown"), Value::as_str)
        .ok_or("Invalid part type")?;
    Ok(Some(match kind {
        "text" => Part::text(text(&part["text"]).into(), time),
        "reasoning" => Part::Reasoning(TextPart {
            text: text(&part["text"]).into(),
            time_created: time,
        }),
        kind if kind == "dynamic-tool" || kind.starts_with("tool-") => {
            let name = if kind == "dynamic-tool" {
                text(&part["toolName"])
            } else {
                &kind[5..]
            };
            let name = if name.is_empty() { "unknown" } else { name };
            let status = match text(&part["state"]) {
                "input-streaming" | "approval-requested"
                | "approval-responded" => "pending",
                "input-available" => "running",
                "output-available" => "completed",
                "output-error" | "output-denied" => "error",
                _ => "unknown",
            };
            Part::tool(
                name,
                text(&part["toolCallId"]),
                json!({"status":status,"input":part["input"],"output":part["output"],"error":part["errorText"],"approval":part["approval"]}),
                time,
            )
        }
        "file" => {
            let url = text(&part["url"]);
            let mime = text(&part["mediaType"]);
            if !url.is_empty() && mime.starts_with("image/") {
                Part::Image(ImagePart {
                    mime_type: Some(mime.into()),
                    data: url.into(),
                    time_created: time,
                })
            } else {
                let label = Some(text(&part["filename"]))
                    .filter(|name| !name.is_empty())
                    .unwrap_or(url);
                if label.is_empty() {
                    return Ok(None);
                }
                Part::text(format!("Attachment: {label}"), time)
            }
        }
        "data-code" | "data-translation" | "data-error" | "data-compact" => {
            let data = object(&part["data"])?;
            Part::text(
                text(
                    &data[if kind == "data-error" {
                        "message"
                    } else {
                        "content"
                    }],
                )
                .into(),
                time,
            )
        }
        _ => Part::event(format!("cherry_{kind}"), part.clone(), time),
    }))
}
