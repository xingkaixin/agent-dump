use crate::desktop::{Kind, has_tables, timestamp};
use crate::provider_error::ProviderError;
use crate::session::{ImagePart, Message, Part, PlanPart, Session, SessionData, Stats, TextPart};
use crate::sqlite::rows;
use crate::timestamp::Timestamp;
use crate::value::{integer, objects, parse_json, string, text, truthy};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::Path;

pub fn sessions(
    connection: &Connection,
    path: &Path,
    id: Option<&str>,
    cutoff: Option<i64>,
) -> crate::Result<Vec<Session>> {
    if !has_tables(
        connection,
        &["new_sessions", "deepchat_sessions", "deepchat_messages"],
    )? {
        return Err(ProviderError::capability(
            [
                "This database does not contain the supported DeepChat session tables.",
                "数据库不包含受支持的 DeepChat 会话表。",
            ],
            [
                "Use the current app_db/agent.db database. Legacy chat.db is not supported.",
                "请使用当前版本的 app_db/agent.db 数据库，暂不支持旧版 chat.db。",
            ],
            vec![path.display().to_string()],
        )
        .into());
    }
    rows(connection, "SELECT s.*, d.model_id, d.provider_id, (SELECT COUNT(*) FROM deepchat_messages m WHERE m.session_id = s.id) AS message_count FROM new_sessions s LEFT JOIN deepchat_sessions d ON d.id = s.id WHERE s.is_draft = 0 AND (? IS NULL OR s.id = ?) AND (? IS NULL OR s.created_at >= ?) ORDER BY s.created_at DESC, s.id", &[&id, &id, &cutoff, &cutoff])?
        .into_iter().map(|row| {
            let mut session = Session::new(string(&row["id"]), if truthy(&row["title"]) { string(&row["title"]) } else { "Untitled".into() }, path.to_owned(), timestamp(&row["created_at"]).unwrap_or(Timestamp::UNIX_EPOCH), timestamp(&row["updated_at"]).unwrap_or(Timestamp::UNIX_EPOCH));
            session.directory = text(&row["project_dir"]).into();
            session.model = text(&row["model_id"]).trim().into();
            session.message_count = row["message_count"].as_u64().map(|v| v as usize);
            session.source_metadata = row;
            Ok(session)
        }).collect()
}

pub fn read(connection: &Connection, session: &Session) -> crate::Result<SessionData> {
    if rows(
        connection,
        "SELECT 1 FROM new_sessions WHERE id = ?",
        &[&session.id],
    )?
    .is_empty()
    {
        return Err(Kind::DeepChat
            .missing_source(&session.source_path, Some(&session.id), Vec::new())
            .into());
    }
    let users = details(
        connection,
        "deepchat_user_messages",
        "message_id",
        &session.id,
    )?;
    let blocks = details(
        connection,
        "deepchat_assistant_blocks",
        "block_index",
        &session.id,
    )?;
    let files = details(
        connection,
        "deepchat_user_message_files",
        "ordinal",
        &session.id,
    )?;
    let links = details(
        connection,
        "deepchat_user_message_links",
        "ordinal",
        &session.id,
    )?;
    let mut messages = Vec::new();
    let mut stats = Stats {
        total_cost: serde_json::Number::from_f64(0.0).unwrap(),
        ..Default::default()
    };
    for row in rows(
        connection,
        "SELECT * FROM deepchat_messages WHERE session_id = ? ORDER BY order_seq, id",
        &[&session.id],
    )? {
        let id = text(&row["id"]);
        let message = decode(
            &row,
            users.get(id).map_or(&[], Vec::as_slice),
            blocks.get(id).map_or(&[], Vec::as_slice),
            files.get(id).map_or(&[], Vec::as_slice),
            links.get(id).map_or(&[], Vec::as_slice),
        )?;
        stats.add_tokens(&message.tokens["input"], &message.tokens["output"])?;
        messages.push(message);
    }
    stats.message_count = messages.len();
    let mut data = session.payload(messages, stats);
    data.directory = session.source_metadata["project_dir"].clone();
    data.extra
        .insert("model".into(), session.source_metadata["model_id"].clone());
    data.extra.insert(
        "parent_session_id".into(),
        session.source_metadata["parent_session_id"].clone(),
    );
    Ok(data)
}

fn details(
    connection: &Connection,
    table: &str,
    order: &str,
    id: &str,
) -> crate::Result<HashMap<String, Vec<Value>>> {
    let mut grouped: HashMap<String, Vec<Value>> = HashMap::new();
    if crate::sqlite::has_table(connection, table)? {
        let columns = if table == "deepchat_user_message_files" {
            "detail.message_id, detail.name, detail.path, detail.mime_type, detail.size"
        } else {
            "detail.*"
        };
        for row in rows(
            connection,
            &format!(
                "SELECT {columns} FROM {table} detail JOIN deepchat_messages m ON m.id = detail.message_id WHERE m.session_id = ? ORDER BY detail.message_id, detail.{order}"
            ),
            &[&id],
        )? {
            grouped
                .entry(string(&row["message_id"]))
                .or_default()
                .push(row);
        }
    }
    Ok(grouped)
}

fn object(raw: &Value) -> Value {
    let parsed = parse_json(raw);
    if parsed.is_object() {
        parsed
    } else {
        json!({})
    }
}

fn decode(
    row: &Value,
    users: &[Value],
    blocks: &[Value],
    files: &[Value],
    links: &[Value],
) -> crate::Result<Message> {
    let metadata = object(&row["metadata"]);
    let time = integer(&row["created_at"]);
    let role = text(&row["role"]);
    let mut message = Message::new(
        string(&row["id"]),
        if metadata["messageType"] == "compaction" {
            "compaction"
        } else {
            role
        },
        time,
        Vec::new(),
    );
    message.model = metadata.get("model").filter(|v| v.is_string()).cloned();
    message.provider = metadata["provider"].as_str().map(str::to_owned);
    message.tokens = json!({"input": crate::value::integer_number(&metadata["inputTokens"]), "output": crate::value::integer_number(&metadata["outputTokens"]), "cache": {"read": crate::value::integer_number(&metadata["cachedInputTokens"]), "write": crate::value::integer_number(&metadata["cacheWriteInputTokens"])}}).as_object().unwrap().clone();
    message.metadata = metadata.as_object().cloned();
    message.extra.insert("status".into(), row["status"].clone());
    if role == "user" {
        let content = parse_json(&row["content"]);
        let raw = if content.is_object() {
            content
        } else {
            json!({"text": text(&content)})
        };
        let body = text(users.first().map_or(&raw["text"], |user| &user["text"]));
        if !body.is_empty() {
            message.parts.push(Part::text(body.into(), time));
        }
        message.extra.insert(
            "links".into(),
            if users.is_empty() {
                raw.get("links").cloned().unwrap_or(json!([]))
            } else {
                links.iter().map(|link| link["url"].clone()).collect()
            },
        );
        let attachments = if users.is_empty() {
            raw["files"].as_array().map_or(&[][..], Vec::as_slice)
        } else {
            files
        };
        message.extra.insert("attachments".into(), attachments.iter().filter(|item| item.is_object()).map(|item| json!({"name":item["name"], "path":item["path"], "mime_type": ([&item["mime_type"], &item["mimeType"], &item["type"]].into_iter().find(|v| truthy(v)).unwrap_or(&item["type"])), "size":item["size"]})).collect());
        return Ok(message);
    }
    let content = if blocks.is_empty() {
        parse_json(&row["content"])
    } else {
        blocks.iter().map(structured_block).collect()
    };
    message.parts = objects(&content)
        .map_err(|_| {
            ProviderError::invalid(format!(
                "Invalid DeepChat assistant content: {}",
                string(&row["id"])
            ))
        })?
        .iter()
        .map(|block| decode_block(block, time))
        .collect::<crate::Result<_>>()?;
    Ok(message)
}

fn structured_block(row: &Value) -> Value {
    let extra = object(&row["extra_json"]);
    let mut tool = object(&extra["toolCallExtra"]);
    for (source, target) in [
        ("tool_call_id", "id"),
        ("tool_name", "name"),
        ("tool_params", "params"),
        ("tool_response", "response"),
    ] {
        tool[target] = row[source].clone();
    }
    json!({"type":row["block_type"], "content":row["text_content"], "status":row["status"], "timestamp":extra.get("timestamp").unwrap_or(&row["updated_at"]), "tool_call":tool, "image_data":{"data":extra["imageData"],"mimeType":row["image_mime_type"]}, "action_type":row["action_type"], "extra":extra["extra"]})
}

fn decode_block(block: &Value, fallback: i64) -> crate::Result<Part> {
    let time = crate::value::integer_or(&block["timestamp"], fallback);
    let body = text(&block["content"]);
    Ok(match text(&block["type"]) {
        "content" | "error" => Part::text(body.into(), time),
        "reasoning_content" => Part::Reasoning(TextPart {
            text: body.into(),
            time_created: time,
        }),
        "tool_call" => {
            let tool = object(&block["tool_call"]);
            let status = match text(&block["status"]) {
                "success" | "granted" => "completed",
                "error" | "denied" => "error",
                "pending" => "pending",
                "loading" => "running",
                _ => "unknown",
            };
            let mut state = json!({"status":status, "input":parse_json(&tool["params"]), "output":tool["response"]});
            if !tool["mcpResult"].is_null() {
                state["mcp_result"] = tool["mcpResult"].clone();
            }
            Part::tool(text(&tool["name"]), text(&tool["id"]), state, time)
        }
        "plan" => Part::Plan(PlanPart {
            input: body.into(),
            output: block["extra"].clone(),
            approval_status: text(&block["status"]).into(),
            time_created: time,
        }),
        "image" => {
            let image = object(&block["image_data"]);
            Part::Image(ImagePart {
                mime_type: image["mimeType"].as_str().map(str::to_owned),
                data: image["data"].clone(),
                time_created: time,
            })
        }
        _ => Part::event(
            format!("deepchat_{}", string(&block["type"])),
            block.clone(),
            time,
        ),
    })
}
