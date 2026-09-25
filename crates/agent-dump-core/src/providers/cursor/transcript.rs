use crate::compat::value::{
    integer, json_object, pretty_json, string, text, truthy,
};
use crate::providers::cursor::{bubbles, build_session, composer};
use crate::session::{
    Message, Part, PlanPart, Session, SessionData, Stats, parse_timestamp,
};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};

pub fn read(
    connection: &Connection,
    session: &Session,
) -> crate::Result<SessionData> {
    let mut frames = vec![Frame::new(connection, session.clone(), None)?];
    let mut expanding = HashSet::new();
    let mut memo: HashMap<String, Option<Message>> = HashMap::new();
    loop {
        let frame = frames.last_mut().unwrap();
        let Some((_, bubble)) = frame.bubbles.peek() else {
            let mut frame = frames.pop().unwrap();
            let id =
                text(&frame.session.source_metadata["composer_id"]).to_owned();
            let composer = frame.composer.take();
            let data = frame.finish();
            let Some(composer) = composer else {
                return Ok(data);
            };
            expanding.remove(&id);
            memo.insert(id.clone(), completion(&id, &composer, &data));
            continue;
        };
        let child_id = bubble
            .as_ref()
            .and_then(|bubble| child_id(&bubble["toolFormerData"]));
        if let Some(id) = &child_id
            && !expanding.contains(id)
            && !memo.contains_key(id)
        {
            if let Some(composer) = composer(connection, id)?.filter(truthy) {
                let session = build_session(
                    &frame.session.source_path,
                    id,
                    id,
                    &composer,
                );
                let child = Frame::new(connection, session, Some(composer))?;
                expanding.insert(id.clone());
                frames.push(child);
                continue;
            }
            memo.insert(id.clone(), None);
        }
        let completion = child_id
            .filter(|id| !expanding.contains(id))
            .and_then(|id| memo.get(&id).cloned().flatten());
        let (id, bubble) = frame.bubbles.next().unwrap();
        frame.append(id, bubble, completion)?;
    }
}

struct Frame {
    session: Session,
    composer: Option<Value>,
    bubbles: std::iter::Peekable<std::vec::IntoIter<(String, Option<Value>)>>,
    messages: Vec<Message>,
    index: HashMap<String, usize>,
    active_model: Option<String>,
    stats: Stats,
}

impl Frame {
    fn new(
        connection: &Connection,
        session: Session,
        composer: Option<Value>,
    ) -> crate::Result<Self> {
        let bubbles = bubbles(
            connection,
            text(&session.source_metadata["composer_id"]),
            true,
            false,
        )?;
        Ok(Self {
            session,
            composer,
            bubbles: bubbles.into_iter().peekable(),
            messages: Vec::new(),
            index: HashMap::new(),
            active_model: None,
            stats: Stats::default(),
        })
    }

    fn append(
        &mut self,
        id: String,
        data: Option<Value>,
        completion: Option<Message>,
    ) -> crate::Result<()> {
        let Some(bubble) = data.filter(truthy) else {
            let mut message = Message::new(
                id,
                "assistant",
                self.session.created_at.as_millisecond(),
                vec![Part::text(
                    "[corrupted message]".into(),
                    self.session.created_at.as_millisecond(),
                )],
            );
            message.agent = Some("cursor".into());
            self.messages.push(message);
            return Ok(());
        };
        let role = if bubble["type"].as_f64() == Some(2.0) {
            "assistant"
        } else {
            "user"
        };
        let time =
            bubble_time(&bubble, self.session.created_at.as_millisecond());
        let model = text(&bubble["modelInfo"]["modelName"]).trim();
        if role == "user" && !model.is_empty() {
            self.active_model = Some(model.to_owned());
        }
        let model = if model.is_empty() {
            self.active_model.clone()
        } else {
            Some(model.to_owned())
        };
        let (input, output) = tokens(&bubble);
        self.stats
            .add_tokens(&input.clone().into(), &output.clone().into())?;
        let body = body(&bubble, role);
        let tool = &bubble["toolFormerData"];
        let plan = if tool["name"] == "create_plan" {
            plan(tool, time)
        } else {
            None
        };
        let (part, completion) = tool_part(tool, time, completion);
        let parent = part.as_ref().and_then(|_| parent(&bubble));
        if let Some(body) = &body {
            let mut message = message(
                &id,
                role,
                model.clone(),
                time,
                input.clone(),
                output.clone(),
                vec![Part::text(body.clone(), time)],
            );
            if let Some(plan) = &plan {
                message.parts.push(plan.clone());
            }
            self.messages.push(message);
            self.index.insert(id.clone(), self.messages.len() - 1);
        }
        if let Some(part) = part {
            if let Some(parent_index) = parent.and_then(|id| self.index.get(id))
            {
                self.messages[*parent_index].parts.push(part);
            } else {
                let mut message = message(
                    &format!("{id}:tool"),
                    "tool",
                    model.clone(),
                    time,
                    0.into(),
                    0.into(),
                    vec![part],
                );
                message.mode = Some("tool".into());
                self.messages.push(message);
            }
        }
        if body.is_none()
            && let Some(plan) = plan
        {
            self.messages.push(message(
                &id,
                "assistant",
                model,
                time,
                input,
                output,
                vec![plan],
            ));
            return Ok(());
        }
        if let Some(completion) = completion {
            self.messages.push(completion);
        }
        Ok(())
    }

    fn finish(mut self) -> SessionData {
        self.messages.sort_by_key(|message| message.time_created);
        self.stats.message_count = self.messages.len();
        for (source, target) in [
            ("contextTokensUsed", "context_tokens_used"),
            ("contextTokenLimit", "context_token_limit"),
            ("contextUsagePercent", "context_usage_percent"),
        ] {
            self.stats.extra.insert(
                target.into(),
                self.session.source_metadata["usage_data"][source].clone(),
            );
        }
        let mut data = self.session.payload(self.messages, self.stats);
        data.directory = Value::Null;
        data.metadata = Some(
            json!({"composer_id":self.session.source_metadata["composer_id"],"request_id":self.session.source_metadata["request_id"],"parent_composer_id":self.session.source_metadata["parent_composer_id"],"subagent_composer_ids":self.session.source_metadata["subagent_composer_ids"]}),
        );
        data
    }
}

fn tool_part(
    data: &Value,
    time: i64,
    completion: Option<Message>,
) -> (Option<Part>, Option<Message>) {
    let name = text(&data["name"]);
    if name.is_empty() || name == "create_plan" {
        return (None, None);
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
            .unwrap_or_else(|| &data["result"]["stderr"]);
        if !error.is_null() {
            state["error"] = error.clone();
        }
    }
    let lowered = name.to_lowercase();
    let subagent = lowered.contains("agent") || lowered.contains("task");
    let mut subagent_id = None;
    if subagent {
        state["prompt"] = prompt(&input).into();
        if !text(&input["subagentType"]).trim().is_empty() {
            state["subagent_type"] = text(&input["subagentType"]).trim().into();
        }
        if let Some(candidate) = child_id(data) {
            subagent_id = Some(candidate.clone());
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
    (Some(part), completion)
}

fn child_id(data: &Value) -> Option<String> {
    let name = text(&data["name"]).to_lowercase();
    if !name.contains("agent") && !name.contains("task") {
        return None;
    }
    let candidate = text(&data["additionalData"]["subagentComposerId"]).trim();
    if !candidate.is_empty() {
        return Some(candidate.into());
    }
    let result = json_object(&data["result"]).unwrap_or(Value::Null);
    let candidate = text(if truthy(&result["agentId"]) {
        &result["agentId"]
    } else {
        &result["agent_id"]
    })
    .trim();
    (!candidate.is_empty()).then(|| candidate.to_owned())
}

fn completion(
    id: &str,
    composer: &Value,
    child: &SessionData,
) -> Option<Message> {
    let mut parts = Vec::new();
    let mut latest = 0;
    for message in child.messages.iter().filter(|m| m.role == "assistant") {
        for part in &message.parts {
            if let Part::Text(part) = part {
                let body = part.text.trim();
                if body.is_empty()
                    || matches!(body, "[empty message]" | "[corrupted message]")
                {
                    continue;
                }
                parts.push(Part::text(body.into(), part.time_created));
                latest = latest.max(part.time_created);
            }
        }
    }
    if parts.is_empty() {
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
            0.into(),
            0.into(),
            parts,
        );
        message.subagent_id = Some(id.into());
        let kind = text(&composer["subagentInfo"]["subagentTypeName"]).trim();
        if !kind.is_empty() {
            message.extra.insert("subagent_type".into(), kind.into());
        }
        Some(message)
    }
}

fn message(
    id: &str,
    role: &str,
    model: Option<String>,
    time: i64,
    input: serde_json::Number,
    output: serde_json::Number,
    parts: Vec<Part>,
) -> Message {
    let mut message = Message::new(id.into(), role, time, parts);
    message.agent = Some("cursor".into());
    message.model = model.map(Value::String);
    message.tokens = serde_json::Map::from_iter([
        ("input".into(), Value::Number(input)),
        ("output".into(), Value::Number(output)),
    ]);
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
        |raw| {
            crate::compat::json::from_str(raw)
                .unwrap_or_else(|_| json!({"_raw":raw}))
        },
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
        .map_or_else(|| pretty_json(input), str::to_owned)
}

fn plan(tool: &Value, time: i64) -> Option<Part> {
    let input = arguments(tool);
    let body = text(&input["plan"]).trim();
    if body.is_empty() {
        return None;
    }
    let result = json_object(&tool["result"]).unwrap_or(Value::Null);
    let rejected = &result["rejected"];
    let output = if rejected.is_null()
        || rejected == &json!({})
        || rejected == &json!([])
    {
        Value::Null
    } else {
        crate::providers::cursor::transcript::compact_json(rejected).into()
    };
    let selected =
        string(&tool["additionalData"]["reviewData"]["selectedOption"])
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

fn tokens(bubble: &Value) -> (serde_json::Number, serde_json::Number) {
    if bubble["tokenCount"].is_object() {
        (
            crate::compat::value::integer_number(
                &bubble["tokenCount"]["inputTokens"],
            ),
            crate::compat::value::integer_number(
                &bubble["tokenCount"]["outputTokens"],
            ),
        )
    } else if bubble["usage"].is_object() {
        (
            crate::compat::value::integer_number(
                &bubble["usage"]["input_tokens"],
            ),
            crate::compat::value::integer_number(
                &bubble["usage"]["output_tokens"],
            ),
        )
    } else {
        (
            crate::compat::value::integer_number(
                &bubble["contextWindowStatusAtCreation"]["tokensUsed"],
            ),
            0.into(),
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
    if role == "assistant"
        && !text(&bubble["thinking"]["text"]).trim().is_empty()
    {
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
        if crate::providers::desktop::timestamp(value).is_some() {
            return integer(value);
        }
    }
    fallback
}
