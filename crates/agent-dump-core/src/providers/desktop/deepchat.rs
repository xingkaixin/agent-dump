use crate::compat::value::{integer, parse_json, string, text};
use crate::providers::desktop::{Kind, has_tables, timestamp};
use crate::providers::error::ProviderError;
use crate::providers::sqlite::connection::{has_table, rows};
use crate::session::timestamp::Timestamp;
use crate::session::{
    ImagePart, Message, Part, PlanPart, Session, SessionData, Stats, TextPart,
};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
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
                "请使用当前版本的 app_db/agent.db 数据库，\
                暂不支持旧版 chat.db。",
            ],
            vec![crate::storage::source_io::path_text(path)],
        )
        .into());
    }
    let mut activity = vec![
        "SELECT MAX(m.updated_at) AS time FROM deepchat_messages m WHERE \
        m.session_id = s.id",
    ];
    if has_table(connection, "deepchat_assistant_blocks")? {
        activity.push(
            "SELECT MAX(b.updated_at) FROM deepchat_assistant_blocks b JOIN \
            deepchat_messages m ON m.id = b.message_id WHERE m.session_id = \
            s.id",
        );
    }
    if has_table(connection, "deepchat_usage_stats")? {
        activity.push(
            "SELECT MAX(u.created_at) FROM deepchat_usage_stats u WHERE \
            u.session_id = s.id",
        );
    }
    let parents: HashMap<String, String> = rows(
        connection,
        "SELECT * FROM new_sessions WHERE is_draft = 0",
        &[],
    )?
    .iter()
    .map(|row| (string(&row["id"]), string(&row["parent_session_id"])))
    .collect();
    rows(
        connection,
        &format!(
            "SELECT s.*, d.model_id, d.provider_id, (SELECT COUNT(*) FROM \
            deepchat_messages m WHERE m.session_id = s.id) AS message_count, \
            (SELECT MAX(time) FROM ({})) AS activity FROM new_sessions s \
            LEFT JOIN deepchat_sessions d ON d.id = s.id WHERE s.is_draft = \
            0 AND (? IS NULL OR s.id = ?) AND (? IS NULL OR s.created_at >= \
            ?) ORDER BY s.created_at DESC, s.id",
            activity.join(" UNION ALL ")
        ),
        &[&id, &id, &cutoff, &cutoff],
    )?
    .into_iter()
    .filter(|row| {
        integer(&row["message_count"]) > 0 && rooted(&parents, text(&row["id"]))
    })
    .map(|row| {
        let updated = [&row["updated_at"], &row["activity"]]
            .into_iter()
            .filter_map(timestamp)
            .max()
            .unwrap_or(Timestamp::UNIX_EPOCH);
        let mut session = Session::new(
            string(&row["id"]),
            title(&row["title"]),
            path.to_owned(),
            timestamp(&row["created_at"]).unwrap_or(Timestamp::UNIX_EPOCH),
            updated,
        );
        session.directory = text(&row["project_dir"]).into();
        session.model = text(&row["model_id"]).trim().into();
        session.message_count = row["message_count"]
            .as_u64()
            .and_then(|v| usize::try_from(v).ok());
        session.source_metadata = row;
        Ok(session)
    })
    .collect()
}

fn rooted(parents: &HashMap<String, String>, id: &str) -> bool {
    let mut seen = HashSet::new();
    let mut node = id;
    while let Some(parent) = parents.get(node) {
        if !seen.insert(node) {
            return false;
        }
        node = parent;
    }
    true
}

fn title(value: &Value) -> String {
    crate::providers::text::clean(text(value))
        .lines()
        .find_map(crate::providers::title::normalize_title)
        .unwrap_or_else(|| "Untitled Session".into())
}

pub fn read(
    connection: &Connection,
    session: &Session,
) -> crate::Result<SessionData> {
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
    let mut ledger = Ledger::default();
    if has_table(connection, "deepchat_usage_stats")? {
        for row in rows(
            connection,
            "SELECT message_id, model_id AS model, provider_id AS provider, \
            input_tokens AS inputTokens, output_tokens AS outputTokens, \
            total_tokens AS totalTokens, cached_input_tokens AS \
            cachedInputTokens, cache_write_input_tokens AS \
            cacheWriteInputTokens FROM deepchat_usage_stats WHERE session_id \
            = ? ORDER BY usage_id",
            &[&session.id],
        )? {
            ledger.add(&row);
        }
    }
    let header = &session.source_metadata;
    let mut messages = Vec::new();
    for row in rows(
        connection,
        "SELECT * FROM deepchat_messages WHERE session_id = ? ORDER BY order_seq, id",
        &[&session.id],
    )? {
        let id = text(&row["id"]);
        let mut metadata = object(&row["metadata"]);
        let mut message = decode(
            &row,
            &metadata,
            users.get(id).map_or(&[], Vec::as_slice),
            blocks.get(id).map_or(&[], Vec::as_slice),
            files.get(id).map_or(&[], Vec::as_slice),
            links.get(id).map_or(&[], Vec::as_slice),
        );
        if row["role"] == "assistant" && !ledger.messages.contains_key(id) {
            metadata["message_id"] = row["id"].clone();
            ledger.add(&metadata);
        }
        let usage = ledger.messages.get(id);
        let [input, output, read, write] = usage.map_or([0; 4], |u| u.tokens);
        message.tokens.clone_from(
            json!({
                "input": input,
                "output": output,
                "cache": {"read": read, "write": write}
            })
            .as_object()
            .unwrap(),
        );
        let fallback = if row["role"] == "assistant" {
            header
        } else {
            &Value::Null
        };
        message.model = usage
            .and_then(|u| u.model.clone())
            .or_else(|| name(&metadata["model"]))
            .or_else(|| name(&fallback["model_id"]))
            .map(Value::String);
        message.provider = usage
            .and_then(|u| u.provider.clone())
            .or_else(|| name(&metadata["provider"]))
            .or_else(|| name(&fallback["provider_id"]));
        messages.push(message);
    }
    crate::providers::text::clean_messages(&mut messages);
    let stats = Stats {
        total_cost: serde_json::Number::from_f64(0.0).unwrap(),
        total_input_tokens: ledger.input.into(),
        total_output_tokens: ledger.output.into(),
        message_count: messages.len(),
        ..Default::default()
    };
    let mut data = session.payload(messages, stats);
    data.directory = header["project_dir"].clone();
    data.extra
        .insert("model".into(), header["model_id"].clone());
    data.extra.insert(
        "parent_session_id".into(),
        header["parent_session_id"].clone(),
    );
    Ok(data)
}

fn name(value: &Value) -> Option<String> {
    value.as_str().filter(|v| !v.is_empty()).map(str::to_owned)
}

#[derive(Default)]
struct Usage {
    model: Option<String>,
    provider: Option<String>,
    tokens: [i64; 4],
}

#[derive(Default)]
struct Ledger {
    messages: HashMap<String, Usage>,
    input: i64,
    output: i64,
}

impl Ledger {
    fn add(&mut self, row: &Value) {
        let tokens = tokens(row);
        if tokens.is_none() && !row["totalTokens"].is_number() {
            return;
        }
        let tokens = tokens.unwrap_or_default();
        let [input, output, ..] = tokens;
        self.input = self.input.saturating_add(input);
        self.output = self.output.saturating_add(output);
        let Some(id) = name(&row["message_id"]) else {
            return;
        };
        let usage = self.messages.entry(id).or_default();
        usage.model = name(&row["model"]);
        usage.provider = name(&row["provider"]);
        for (sum, value) in usage.tokens.iter_mut().zip(tokens) {
            *sum = sum.saturating_add(value);
        }
    }
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "Token counts are integral; out-of-range values saturate"
)]
fn count(value: &Value) -> i64 {
    value.as_f64().unwrap_or(0.0) as i64
}

fn tokens(row: &Value) -> Option<[i64; 4]> {
    if !row["inputTokens"].is_number() && !row["outputTokens"].is_number() {
        return None;
    }
    let raw = count(&row["inputTokens"]);
    let input = raw.max(0);
    let read = count(&row["cachedInputTokens"]).max(0);
    let write = count(&row["cacheWriteInputTokens"]).max(0);
    Some([
        input,
        count(&row["outputTokens"]).max(0),
        read.min(input),
        write.min(raw.saturating_sub(read).max(0)),
    ])
}

fn details(
    connection: &Connection,
    table: &str,
    order: &str,
    id: &str,
) -> crate::Result<HashMap<String, Vec<Value>>> {
    let mut grouped: HashMap<String, Vec<Value>> = HashMap::new();
    if has_table(connection, table)? {
        let columns = if table == "deepchat_user_message_files" {
            "detail.message_id, detail.name, detail.path, detail.mime_type, detail.size"
        } else {
            "detail.*"
        };
        for row in rows(
            connection,
            &format!(
                "SELECT {columns} FROM {table} detail JOIN deepchat_messages \
                m ON m.id = detail.message_id WHERE m.session_id = ? ORDER \
                BY detail.message_id, detail.{order}"
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
    metadata: &Value,
    users: &[Value],
    blocks: &[Value],
    files: &[Value],
    links: &[Value],
) -> Message {
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
    message.metadata = metadata.as_object().cloned();
    message.extra.insert("status".into(), row["status"].clone());
    if role == "user" {
        let content = parse_json(&row["content"]);
        let raw = if content.is_object() {
            content
        } else {
            json!({"text": text(&content)})
        };
        let body =
            text(users.first().map_or(&raw["text"], |user| &user["text"]));
        let mut labels = vec![body.to_owned()];
        for item in raw["inlineItems"].as_array().into_iter().flatten() {
            if item["type"] != "session" {
                continue;
            }
            let Some(id) = item["sessionId"].as_str() else {
                continue;
            };
            labels.push(match name(&item["title"]) {
                Some(title) => format!("Session: {title} ({id})"),
                None => format!("Session: {id}"),
            });
        }
        let attachments: Vec<&Value> = if users.is_empty() {
            raw["files"].as_array().map_or(&[][..], Vec::as_slice)
        } else {
            files
        }
        .iter()
        .filter(|item| item.is_object())
        .collect();
        labels.extend(attachments.iter().filter_map(|item| {
            name(&item["path"])
                .or_else(|| name(&item["name"]))
                .map(|label| format!("Attachment: {label}"))
        }));
        let links = if users.is_empty() {
            raw.get("links").cloned().unwrap_or(json!([]))
        } else {
            links.iter().map(|link| link["url"].clone()).collect()
        };
        labels.extend(links.as_array().into_iter().flatten().filter_map(name));
        message.parts = labels
            .into_iter()
            .filter(|label| !label.is_empty())
            .map(|label| Part::text(label, time))
            .collect();
        message.extra.insert("links".into(), links);
        message.extra.insert(
            "attachments".into(),
            attachments
                .iter()
                .map(|item| {
                    let mime_type =
                        [&item["mime_type"], &item["mimeType"], &item["type"]]
                            .into_iter()
                            .find(|v| crate::compat::value::truthy(v))
                            .unwrap_or_else(|| &item["type"]);
                    json!({
                        "name": item["name"],
                        "path": item["path"],
                        "mime_type": mime_type,
                        "size": item["size"]
                    })
                })
                .collect(),
        );
        return message;
    }
    let content = if blocks.is_empty() {
        parse_json(&row["content"])
    } else {
        blocks.iter().map(structured_block).collect()
    };
    message.parts = match &content {
        Value::Array(blocks) => blocks
            .iter()
            .filter_map(|block| decode_block(block, time))
            .collect(),
        Value::String(body) if !body.is_empty() => {
            vec![Part::text(body.clone(), time)]
        }
        _ => Vec::new(),
    };
    message
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
    json!({
        "type": row["block_type"],
        "content": row["text_content"],
        "status": row["status"],
        "timestamp": extra
            .get("timestamp")
            .unwrap_or_else(|| &row["updated_at"]),
        "tool_call": tool,
        "image_data": {
            "data": extra["imageData"],
            "mimeType": row["image_mime_type"]
        },
        "action_type": row["action_type"],
        "extra": extra["extra"]
    })
}

fn decode_block(block: &Value, fallback: i64) -> Option<Part> {
    let time = crate::compat::value::integer_or(&block["timestamp"], fallback);
    let body = text(&block["content"]);
    match text(&block["type"]) {
        "tool_call" => {
            let tool = object(&block["tool_call"]);
            let status = match text(&block["status"]) {
                "success" | "granted" => "completed",
                "error" | "denied" => "error",
                "pending" => "pending",
                "loading" => "running",
                _ => "unknown",
            };
            let mut state = json!({
                "status": status,
                "input": parse_json(&tool["params"]),
                "output": tool["response"]
            });
            if status == "error" {
                if !tool["response"].is_null() {
                    state["error"] = tool["response"].clone();
                } else if !body.is_empty() {
                    state["error"] = body.into();
                }
            }
            if !tool["mcpResult"].is_null() {
                state["mcp_result"] = tool["mcpResult"].clone();
            }
            return Some(Part::tool(
                text(&tool["name"]),
                text(&tool["id"]),
                state,
                time,
            ));
        }
        "plan" => {
            return Some(Part::Plan(PlanPart {
                input: body.into(),
                output: block["extra"].clone(),
                approval_status: text(&block["status"]).into(),
                time_created: time,
            }));
        }
        "image" => {
            let image = object(&block["image_data"]);
            if let Some((data, mime)) =
                name(&image["data"]).zip(name(&image["mimeType"]))
            {
                return Some(Part::Image(ImagePart {
                    mime_type: Some(mime),
                    data: data.into(),
                    time_created: time,
                }));
            }
        }
        _ => {}
    }
    if body.is_empty() {
        return None;
    }
    Some(if block["type"] == "reasoning_content" {
        Part::Reasoning(TextPart {
            text: body.into(),
            time_created: time,
        })
    } else {
        Part::text(body.into(), time)
    })
}
