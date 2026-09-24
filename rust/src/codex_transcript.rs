use crate::codex::text;
use crate::jsonl;
use crate::session::{Message, Part, Session, SessionData, Stats, parse_timestamp};
use serde_json::Value;

fn unsupported(detail: &str) -> Box<dyn std::error::Error> {
    format!("Rust P1 does not yet support {detail}; use the Python CLI for this session").into()
}

fn text_parts(payload: &Value, timestamp: i64, reasoning: bool) -> crate::Result<Vec<Part>> {
    let field = if reasoning { "summary" } else { "content" };
    let Some(content) = payload[field].as_array() else {
        return Err(unsupported("non-array Codex message content"));
    };
    let expected = if reasoning {
        "summary_text"
    } else if payload["role"] == "assistant" {
        "output_text"
    } else {
        "input_text"
    };
    let mut parts = Vec::new();
    for item in content {
        if item["type"] != expected || !item["text"].is_string() {
            return Err(unsupported("non-text Codex content"));
        }
        let body = text(&item["text"]);
        let lower = body.to_lowercase();
        if [
            "<proposed_plan>",
            "<subagent_notification>",
            "<skill>",
            "<instructions>",
            "<skills_instructions>",
            "<apps_instructions>",
            "<plugins_instructions>",
            "<recommended_plugins>",
            "<environment_context>",
            "<permissions instructions>",
            "<collaboration_mode>",
            "<multi_agent_mode>",
        ]
        .iter()
        .any(|tag| lower.contains(tag))
        {
            return Err(unsupported(
                "Codex plan, injected context, skill or subagent messages",
            ));
        }
        parts.push(Part {
            kind: if reasoning { "reasoning" } else { "text" }.into(),
            text: body.to_owned(),
            time_created: timestamp,
        });
    }
    Ok(parts)
}

fn token_count(value: &Value) -> i64 {
    value
        .as_i64()
        .or_else(|| value.as_str().and_then(|v| v.trim().parse().ok()))
        .or_else(|| value.as_f64().map(|v| v as i64))
        .unwrap_or(0)
}

pub fn read(session: &Session) -> crate::Result<SessionData> {
    let mut messages: Vec<Message> = Vec::new();
    let mut current: Option<usize> = None;
    let mut stats = Stats::default();
    jsonl::scan(&session.source_path, |record| {
        let payload = &record["payload"];
        let usage = &payload["info"]["total_token_usage"];
        stats.total_input_tokens += token_count(&usage["input_tokens"]);
        stats.total_output_tokens += token_count(&usage["output_tokens"]);
        if record["type"] != "response_item" {
            return Ok(());
        }
        let reasoning = match text(&payload["type"]) {
            "message" => false,
            "reasoning" => true,
            other => return Err(unsupported(&format!("Codex response item {other:?}"))),
        };
        let timestamp =
            parse_timestamp(text(&record["timestamp"])).map_or(0, |time| time.as_millisecond());
        let role = if reasoning {
            "assistant"
        } else {
            text(&payload["role"])
        };
        let parts = text_parts(payload, timestamp, reasoning)?;
        if parts.is_empty() {
            return Ok(());
        }
        if role == "assistant"
            && let Some(index) = current
            && (!reasoning || !messages[index].parts.iter().any(|part| part.kind == "text"))
        {
            for part in parts {
                if messages[index].parts.last() != Some(&part) {
                    messages[index].parts.push(part);
                }
            }
            return Ok(());
        }
        let role = match role {
            "user" | "assistant" | "developer" | "system" | "tool" => role,
            _ => "unknown",
        };
        messages.push(Message {
            id: text(&record["timestamp"]).to_owned(),
            role: role.into(),
            agent: (role == "assistant").then(|| "codex".into()),
            mode: None,
            model: None,
            provider: None,
            time_created: timestamp,
            time_completed: None,
            tokens: Default::default(),
            cost: 0,
            parts,
        });
        current = (role == "assistant").then_some(messages.len() - 1);
        Ok(())
    })?;
    stats.message_count = messages.len();
    Ok(SessionData {
        id: session.id.clone(),
        title: session.title.clone(),
        slug: None,
        directory: session.directory.clone(),
        version: session.version.clone(),
        time_created: session.created_at.as_millisecond(),
        time_updated: session.updated_at.as_millisecond(),
        summary_files: None,
        stats,
        messages,
    })
}
