use crate::compat::value::{integer, objects, string, text, truthy};
use crate::providers::desktop::{Kind, has_tables, timestamp};
use crate::providers::error::ProviderError;
use crate::providers::sqlite::connection::rows;
use crate::session::timestamp::Timestamp;
use crate::session::{Message, Part, Session, SessionData, Stats, TextPart};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

pub fn search_roots() -> crate::Result<Vec<(&'static str, PathBuf)>> {
    if let Some(root) = std::env::var_os("CHERRY_STUDIO_USER_DATA_DIR")
        .filter(|v| !v.is_empty())
    {
        return Ok(vec![(
            "Cherry Studio userData",
            PathBuf::from(root).join("Data/cherrystudio.sqlite"),
        )]);
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
    let deleted = rows(connection, "PRAGMA table_info(agent_session)", &[])?
        .iter()
        .any(|row| row["name"] == "deleted_at");
    let filter = if deleted {
        "WHERE s.deleted_at IS NULL"
    } else {
        ""
    };
    rows(
        connection,
        &format!(
            "SELECT * FROM (SELECT 'topic-' || id AS session_id, 'topic' AS kind, id, name, created_at, updated_at, active_node_id, NULL AS directory FROM topic WHERE deleted_at IS NULL UNION ALL SELECT 'session-' || s.id, 'session', s.id, s.name, s.created_at, s.updated_at, NULL, w.path FROM agent_session s LEFT JOIN agent_workspace w ON w.id = s.workspace_id {filter}) WHERE (? IS NULL OR session_id = ?) AND (? IS NULL OR created_at >= ?) ORDER BY created_at DESC, session_id"
        ),
        &[&id, &id, &cutoff, &cutoff],
    )
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
            Ok(session) => result.sessions.push(session),
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
) -> crate::Result<Session> {
    let messages = message_rows(connection, row, false)?;
    let mut model = String::new();
    for message in messages.iter().rev().filter(|m| m["role"] == "assistant") {
        let (candidate, _) = message_model(message)?;
        if truthy(&candidate) {
            model = text(&candidate).into();
            break;
        }
    }
    let mut session = Session::new(
        string(&row["session_id"]),
        if truthy(&row["name"]) {
            string(&row["name"])
        } else {
            "Untitled".into()
        },
        path.to_owned(),
        timestamp(&row["created_at"]).unwrap_or(Timestamp::UNIX_EPOCH),
        timestamp(&row["updated_at"]).unwrap_or(Timestamp::UNIX_EPOCH),
    );
    session.directory = text(&row["directory"]).into();
    session.model = model.trim().into();
    session.message_count = Some(messages.len());
    Ok(session)
}

fn message_rows(
    connection: &Connection,
    session: &Value,
    full: bool,
) -> crate::Result<Vec<Value>> {
    let columns = if full {
        "m.*"
    } else {
        "m.id, m.role, m.model_id, m.message_snapshot"
    };
    let id = text(&session["id"]);
    if session["kind"] == "session" {
        return rows(
            connection,
            &format!(
                "SELECT {columns} FROM agent_session_message m WHERE session_id = ? ORDER BY created_at, id"
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
        &format!(
            "WITH RECURSIVE branch(id, parent_id) AS (SELECT id, parent_id FROM message WHERE id = ? AND topic_id = ? AND deleted_at IS NULL UNION SELECT m.id, m.parent_id FROM message m JOIN branch b ON m.id = b.parent_id WHERE m.topic_id = ? AND m.deleted_at IS NULL) SELECT {columns}, m.parent_id, json_array_length(m.data, '$.parts') AS parts_count FROM message m JOIN branch b ON m.id = b.id"
        ),
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
        if !(node == active
            && row["role"] == "user"
            && !truthy(&row["parts_count"]))
        {
            chain.push(row.clone());
        }
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
    let messages = message_rows(connection, &row, true)?
        .iter()
        .map(decode)
        .collect::<crate::Result<Vec<_>>>()?;
    let mut stats = Stats {
        total_cost: serde_json::Number::from_f64(0.0).unwrap(),
        message_count: messages.len(),
        ..Default::default()
    };
    for message in &messages {
        stats
            .add_tokens(&message.tokens["input"], &message.tokens["output"])?;
    }
    let mut data = session.payload(messages, stats);
    data.title = if truthy(&row["name"]) {
        string(&row["name"])
    } else {
        "Untitled".into()
    };
    data.directory = row["directory"].clone();
    data.time_created = integer(&row["created_at"]);
    data.time_updated = integer(&row["updated_at"]);
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

fn decode(row: &Value) -> crate::Result<Message> {
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
    let cache = object(&stats["inputTokenDetails"])?;
    let time = integer(&row["created_at"]);
    let mut message =
        Message::new(string(&row["id"]), text(&row["role"]), time, Vec::new());
    message.model = model.as_str().map(std::convert::Into::into);
    message.provider = provider.as_str().map(str::to_owned);
    message.tokens.clone_from(json!({"input":crate::compat::value::integer_number(&stats["inputTokens"]), "output":crate::compat::value::integer_number(&stats["outputTokens"]), "cache":{"read":crate::compat::value::integer_number(&cache["cacheReadTokens"]),"write":crate::compat::value::integer_number(&cache["cacheWriteTokens"])}}).as_object().unwrap());
    message.extra.insert("status".into(), row["status"].clone());
    message.extra.insert(
        "costs".into(),
        stats.get("costs").cloned().unwrap_or(json!([])),
    );
    for part in objects(data.get("parts").unwrap_or(&json!([])))? {
        message.parts.push(decode_part(part, time)?);
    }
    Ok(message)
}

fn decode_part(part: &Value, time: i64) -> crate::Result<Part> {
    let kind = part
        .get("type")
        .map_or(Some("unknown"), Value::as_str)
        .ok_or("Invalid part type")?;
    Ok(match kind {
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
        "data-code" | "data-translation" | "data-error" => {
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
    })
}
