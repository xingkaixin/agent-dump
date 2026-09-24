use crate::cursor::{bubbles, build_session, composer};
use crate::session::{Message, Part, PlanPart, Session, SessionData, Stats, parse_timestamp};
use crate::value::{integer, json_object, pretty_json, string, text, truthy};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};

pub fn read(connection: &Connection, session: &Session) -> crate::Result<SessionData> {
    Decoder {
        connection,
        expanding: HashSet::new(),
        memo: HashMap::new(),
    }
    .session(session)
}

struct Decoder<'a> {
    connection: &'a Connection,
    expanding: HashSet<String>,
    memo: HashMap<String, Option<Message>>,
}

impl Decoder<'_> {
    fn session(&mut self, session: &Session) -> crate::Result<SessionData> {
        let composer_id = text(&session.source_metadata["composer_id"]);
        let fallback = session.created_at.as_millisecond();
        let mut messages: Vec<Message> = Vec::new();
        let mut index: HashMap<String, usize> = HashMap::new();
        let mut active_model = None;
        let mut stats = Stats::default();
        for (id, data) in bubbles(self.connection, composer_id, true, false)? {
            let Some(bubble) = data.filter(truthy) else {
                let mut message = Message::new(
                    id,
                    "assistant",
                    fallback,
                    vec![Part::text("[corrupted message]".into(), fallback)],
                );
                message.agent = Some("cursor".into());
                messages.push(message);
                continue;
            };
            let role = if bubble["type"].as_f64() == Some(2.0) {
                "assistant"
            } else {
                "user"
            };
            let time = bubble_time(&bubble, fallback);
            let model = text(&bubble["modelInfo"]["modelName"]).trim();
            if role == "user" && !model.is_empty() {
                active_model = Some(model.to_owned());
            }
            let model = if model.is_empty() {
                active_model.clone()
            } else {
                Some(model.to_owned())
            };
            let (input, output) = tokens(&bubble);
            stats.add_tokens(&input.into(), &output.into())?;
            let body = body(&bubble, role);
            let tool = &bubble["toolFormerData"];
            let plan = if tool["name"] == "create_plan" {
                plan(tool, time)
            } else {
                None
            };
            let (part, completion) = self.tool(tool, time, session)?;
            let parent = part.as_ref().and_then(|_| parent(&bubble));
            if let Some(body) = &body {
                let mut message = message(
                    &id,
                    role,
                    model.clone(),
                    time,
                    input,
                    output,
                    vec![Part::text(body.clone(), time)],
                );
                if let Some(plan) = &plan {
                    message.parts.push(plan.clone());
                }
                messages.push(message);
                index.insert(id.clone(), messages.len() - 1);
            }
            if let Some(part) = part {
                if let Some(parent_index) = parent.and_then(|id| index.get(id)) {
                    messages[*parent_index].parts.push(part);
                } else {
                    let mut message = message(
                        &format!("{id}:tool"),
                        "tool",
                        model.clone(),
                        time,
                        0,
                        0,
                        vec![part],
                    );
                    message.mode = Some("tool".into());
                    messages.push(message);
                }
            }
            if body.is_none()
                && let Some(plan) = plan
            {
                messages.push(message(
                    &id,
                    "assistant",
                    model,
                    time,
                    input,
                    output,
                    vec![plan],
                ));
                continue;
            }
            if let Some(completion) = completion {
                messages.push(completion);
            }
        }
        messages.sort_by_key(|message| message.time_created);
        stats.message_count = messages.len();
        for (source, target) in [
            ("contextTokensUsed", "context_tokens_used"),
            ("contextTokenLimit", "context_token_limit"),
            ("contextUsagePercent", "context_usage_percent"),
        ] {
            stats.extra.insert(
                target.into(),
                session.source_metadata["usage_data"][source].clone(),
            );
        }
        let mut data = session.payload(messages, stats);
        data.directory = Value::Null;
        data.metadata = Some(
            json!({"composer_id":session.source_metadata["composer_id"],"request_id":session.source_metadata["request_id"],"parent_composer_id":session.source_metadata["parent_composer_id"],"subagent_composer_ids":session.source_metadata["subagent_composer_ids"]}),
        );
        Ok(data)
    }

    fn tool(
        &mut self,
        data: &Value,
        time: i64,
        session: &Session,
    ) -> crate::Result<(Option<Part>, Option<Message>)> {
        let name = text(&data["name"]);
        if name.is_empty() || name == "create_plan" {
            return Ok((None, None));
        }
        let input = arguments(data);
        let raw_status = if truthy(&data["additionalData"]["status"]) {
            &data["additionalData"]["status"]
        } else {
            &data["status"]
        };
        let mut state = json!({"status":if raw_status.is_null() { Value::Null } else { string(raw_status).into() },"arguments":input,"output":data["result"]});
        if data["result"].is_object() {
            let error = ["error", "message"]
                .iter()
                .map(|k| &data["result"][k])
                .find(|v| truthy(v))
                .unwrap_or(&data["result"]["stderr"]);
            if !error.is_null() {
                state["error"] = error.clone();
            }
        }
        let lowered = name.to_lowercase();
        let subagent = lowered.contains("agent") || lowered.contains("task");
        let mut completion = None;
        let mut subagent_id = None;
        if subagent {
            state["prompt"] = prompt(&input).into();
            if !text(&input["subagentType"]).trim().is_empty() {
                state["subagent_type"] = text(&input["subagentType"]).trim().into();
            }
            let result = json_object(&data["result"]).unwrap_or(Value::Null);
            let candidate = text(&data["additionalData"]["subagentComposerId"]).trim();
            let candidate = if candidate.is_empty() {
                text(if truthy(&result["agentId"]) {
                    &result["agentId"]
                } else {
                    &result["agent_id"]
                })
                .trim()
            } else {
                candidate
            };
            if !candidate.is_empty() {
                subagent_id = Some(candidate.to_owned());
                completion = self.completion(candidate, session)?;
                if let Some(child) = &completion {
                    if let Some(model) = &child.model
                        && truthy(model)
                    {
                        state["model"] = model.clone();
                    }
                    if let Some(kind) = child.extra.get("subagent_type") {
                        state["subagent_type"] = kind.clone();
                    }
                }
                state["output"] = Value::Null;
                state["subagent_id"] = candidate.into();
            }
        }
        let call_id = if truthy(&data["toolCallId"]) {
            &data["toolCallId"]
        } else {
            &data["callId"]
        };
        let mut part = Part::tool(
            if subagent { "subagent" } else { name },
            text(call_id),
            state,
            time,
        );
        if let Part::Tool(tool) = &mut part {
            tool.title = name.into();
            tool.subagent_id = subagent_id;
            if tool.subagent_id.is_some() {
                tool.subagent_type = tool
                    .state
                    .get("subagent_type")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
            }
        }
        Ok((Some(part), completion))
    }

    fn completion(&mut self, id: &str, parent: &Session) -> crate::Result<Option<Message>> {
        if self.expanding.contains(id) {
            return Ok(None);
        }
        if let Some(message) = self.memo.get(id) {
            return Ok(message.clone());
        }
        let Some(composer) = composer(self.connection, id)?.filter(truthy) else {
            self.memo.insert(id.into(), None);
            return Ok(None);
        };
        let session = build_session(&parent.source_path, id, id, &composer);
        self.expanding.insert(id.into());
        let child = self.session(&session);
        self.expanding.remove(id);
        let child = child?;
        let mut parts = Vec::new();
        let mut latest = 0;
        for message in child.messages.iter().filter(|m| m.role == "assistant") {
            for part in &message.parts {
                if let Part::Text(part) = part {
                    let body = part.text.trim();
                    if body.is_empty() || matches!(body, "[empty message]" | "[corrupted message]")
                    {
                        continue;
                    }
                    parts.push(Part::text(body.into(), part.time_created));
                    latest = latest.max(part.time_created);
                }
            }
        }
        let result = if parts.is_empty() {
            None
        } else {
            let model = text(&composer["modelConfig"]["modelName"]).trim();
            let model = if model.is_empty() {
                child
                    .messages
                    .iter()
                    .filter_map(|m| m.model.as_ref().and_then(Value::as_str))
                    .map(str::trim)
                    .find(|v| !v.is_empty())
                    .map(str::to_owned)
            } else {
                Some(model.to_owned())
            };
            let mut message = message(
                &format!("{id}:subagent-output"),
                "assistant",
                model,
                latest,
                0,
                0,
                parts,
            );
            message.subagent_id = Some(id.into());
            let kind = text(&composer["subagentInfo"]["subagentTypeName"]).trim();
            if !kind.is_empty() {
                message.extra.insert("subagent_type".into(), kind.into());
            }
            Some(message)
        };
        self.memo.insert(id.into(), result.clone());
        Ok(result)
    }
}

fn message(
    id: &str,
    role: &str,
    model: Option<String>,
    time: i64,
    input: i64,
    output: i64,
    parts: Vec<Part>,
) -> Message {
    let mut message = Message::new(id.into(), role, time, parts);
    message.agent = Some("cursor".into());
    message.model = model.map(Value::String);
    message.tokens = json!({"input":input,"output":output})
        .as_object()
        .unwrap()
        .clone();
    message
}

fn arguments(tool: &Value) -> Value {
    let input = if tool["params"].is_null() {
        &tool["rawArgs"]
    } else {
        &tool["params"]
    };
    input.as_str().map_or_else(
        || input.clone(),
        |raw| serde_json::from_str(raw).unwrap_or_else(|_| json!({"_raw":raw})),
    )
}

fn prompt(input: &Value) -> String {
    for name in ["prompt", "description"] {
        let value = text(&input[name]).trim();
        if !value.is_empty() {
            return value.into();
        }
    }
    input
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| pretty_json(input))
}

fn plan(tool: &Value, time: i64) -> Option<Part> {
    let input = arguments(tool);
    let body = text(&input["plan"]).trim();
    if body.is_empty() {
        return None;
    }
    let result = json_object(&tool["result"]).unwrap_or(Value::Null);
    let rejected = &result["rejected"];
    let output = if rejected.is_null() || rejected == &json!({}) || rejected == &json!([]) {
        Value::Null
    } else {
        crate::cursor_transcript::compact_json(rejected).into()
    };
    let selected = string(&tool["additionalData"]["reviewData"]["selectedOption"])
        .trim()
        .to_lowercase();
    let status = if matches!(
        selected.as_str(),
        "accept" | "accepted" | "approve" | "approved"
    ) {
        "success"
    } else {
        "fail"
    };
    Some(Part::Plan(PlanPart {
        input: body.into(),
        output,
        approval_status: status.into(),
        time_created: time,
    }))
}

fn compact_json(value: &Value) -> String {
    match value {
        Value::Array(items) => format!(
            "[{}]",
            items
                .iter()
                .map(compact_json)
                .collect::<Vec<_>>()
                .join(", ")
        ),
        Value::Object(items) => format!(
            "{{{}}}",
            items
                .iter()
                .map(|(key, value)| format!(
                    "{}: {}",
                    serde_json::to_string(key).unwrap(),
                    compact_json(value)
                ))
                .collect::<Vec<_>>()
                .join(", ")
        ),
        _ => serde_json::to_string(value).unwrap(),
    }
}

fn parent(bubble: &Value) -> Option<&str> {
    let tool = &bubble["toolFormerData"];
    let additional = &tool["additionalData"];
    [
        &bubble["parentMessageId"],
        &bubble["parentBubbleId"],
        &tool["parentMessageId"],
        &tool["parentBubbleId"],
        &tool["messageId"],
        &additional["parentMessageId"],
        &additional["parentBubbleId"],
        &additional["messageId"],
    ]
    .into_iter()
    .filter_map(Value::as_str)
    .map(str::trim)
    .find(|v| !v.is_empty())
}

fn tokens(bubble: &Value) -> (i64, i64) {
    if bubble["tokenCount"].is_object() {
        (
            integer(&bubble["tokenCount"]["inputTokens"]),
            integer(&bubble["tokenCount"]["outputTokens"]),
        )
    } else if bubble["usage"].is_object() {
        (
            integer(&bubble["usage"]["input_tokens"]),
            integer(&bubble["usage"]["output_tokens"]),
        )
    } else {
        (
            integer(&bubble["contextWindowStatusAtCreation"]["tokensUsed"]),
            0,
        )
    }
}

fn body(bubble: &Value, role: &str) -> Option<String> {
    if role == "assistant" && !text(&bubble["text"]).trim().is_empty() {
        return Some(text(&bubble["text"]).trim().into());
    }
    let chunks: Vec<_> = bubble["codeBlocks"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|v| text(&v["content"]).trim())
        .filter(|v| !v.is_empty())
        .collect();
    if !chunks.is_empty() {
        return Some(chunks.join("\n\n"));
    }
    if role == "assistant" && !text(&bubble["thinking"]["text"]).trim().is_empty() {
        return Some(text(&bubble["thinking"]["text"]).trim().into());
    }
    [
        "text",
        "content",
        "finalText",
        "message",
        "markdown",
        "textDescription",
    ]
    .iter()
    .map(|name| text(&bubble[name]).trim())
    .find(|v| !v.is_empty())
    .map(str::to_owned)
}

fn bubble_time(bubble: &Value, fallback: i64) -> i64 {
    if let Some(time) = bubble["createdAt"].as_str().and_then(parse_timestamp) {
        return time.as_millisecond();
    }
    for name in ["clientRpcSendTime", "clientSettleTime", "clientEndTime"] {
        let value = &bubble["timingInfo"][name];
        if crate::desktop::timestamp(value).is_some() {
            return integer(value);
        }
    }
    fallback
}
