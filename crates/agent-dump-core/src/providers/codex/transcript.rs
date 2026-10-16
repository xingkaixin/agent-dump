use crate::compat::value::{field, parsed_string, string, text, truthy};
use crate::providers::codex::enrichment::{
    context, output_parts, record_subagent_output, subagent_notification,
    user_text,
};
use crate::providers::codex::usage::Usage;
use crate::providers::codex::{children, exec, rollout};
use crate::providers::contract::RecoverableDiagnostic;
use crate::session::assembly::AssistantFold;
use crate::session::{
    Message, Part, PlanPart, Session, SessionData, Stats, TextPart, ToolPart,
    parse_timestamp,
};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Default)]
struct Decoder {
    messages: Vec<Message>,
    pending_calls: HashMap<String, (usize, usize)>,
    nicknames: HashMap<String, String>,
    current_assistant: Option<usize>,
    assistant_fold: AssistantFold,
    latest_assistant_text: Option<usize>,
    pending_plan: Option<(usize, usize)>,
    model: Option<String>,
    usage: Option<Usage>,
}

fn split_plan(body: &str) -> Option<(&str, &str, &str)> {
    let (before, rest) = body.split_once("<proposed_plan>")?;
    let (plan, after) = rest.split_once("</proposed_plan>")?;
    let plan = plan.trim();
    (!plan.is_empty()).then_some((before.trim(), plan, after.trim()))
}

fn content_parts(payload: &Value, timestamp: i64) -> crate::Result<Vec<Part>> {
    let assistant = payload["role"] == "assistant";
    let expected = if assistant {
        "output_text"
    } else {
        "input_text"
    };
    let Some(items) = payload["content"].as_array() else {
        return Ok(Vec::new());
    };
    let mut parts = Vec::new();
    for item in items {
        if matches!(item["type"], Value::Array(_) | Value::Object(_)) {
            return Err(format!(
                "unhashable type: '{}'",
                crate::compat::value::type_name(&item["type"])
            )
            .into());
        }
        if item["type"] != expected {
            continue;
        }
        let body = field(item, "text");
        if assistant && let Some((before, plan, after)) = split_plan(&body) {
            if !before.is_empty() {
                parts.push(Part::text(before.into(), timestamp));
            }
            parts.push(Part::Plan(PlanPart {
                input: plan.into(),
                output: Value::Null,
                approval_status: "fail".into(),
                time_created: timestamp,
            }));
            if !after.is_empty() {
                parts.push(Part::text(after.into(), timestamp));
            }
            continue;
        }
        parts.push(Part::text(body, timestamp));
    }
    Ok(parts)
}

fn reasoning_part(payload: &Value, timestamp: i64) -> Option<Part> {
    let text = payload["summary"]
        .as_array()?
        .iter()
        .filter(|item| item["type"] == "summary_text")
        .filter_map(|item| item["text"].as_str())
        .filter(|text| !text.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n");
    (!text.is_empty()).then_some(Part::Reasoning(TextPart {
        text,
        time_created: timestamp,
    }))
}

fn tool_name(name: &str, namespace: &str) -> String {
    match name {
        "exec_command" => return "bash".into(),
        "apply_patch" | "patch" => return "patch".into(),
        "spawn_agent" | "subagent" => return "subagent".into(),
        _ => {}
    }
    if namespace.is_empty() {
        return name.into();
    }
    let suffix = namespace.rsplit("__").next().unwrap_or(namespace);
    let normalized = match name.trim_start_matches(['_', '.']) {
        "" => name,
        normalized => normalized,
    };
    if suffix.is_empty() {
        normalized.into()
    } else {
        format!("{suffix}.{normalized}")
    }
}

fn tool_search_text(payload: &Value) -> String {
    payload["tools"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|tool| {
            let name = text(&tool["name"]);
            let nested = tool["tools"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|tool| tool["name"].as_str())
                .collect::<Vec<_>>()
                .join(", ");
            if nested.is_empty() {
                name.to_owned()
            } else {
                format!("{name}: {nested}")
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

impl Decoder {
    fn record(&mut self, record: &Value, zh: bool) -> crate::Result<()> {
        let payload = &record["payload"];
        let usage = self.usage.get_or_insert_with(|| Usage::new(payload));
        match text(&record["type"]) {
            "session_meta" | "turn_context" => {
                if let Some(model) = super::meta_model(record) {
                    self.model = Some(model);
                }
                if record["type"] == "turn_context" {
                    usage.turn(payload);
                }
                return Ok(());
            }
            "event_msg" if payload["type"] == "token_count" => {
                usage.consume(payload);
                return Ok(());
            }
            "token_usage_record" => {
                usage.record(payload);
                return Ok(());
            }
            "compacted" => {
                usage.compacted(payload);
                return Ok(());
            }
            "response_item" if payload.is_object() => {}
            _ => return Ok(()),
        }
        if matches!(payload["type"], Value::Array(_) | Value::Object(_)) {
            return Err(format!(
                "unhashable type: '{}'",
                crate::compat::value::type_name(&payload["type"])
            )
            .into());
        }
        let id = field(record, "timestamp");
        let timestamp = parse_timestamp(id.trim())
            .map_or(0, crate::session::timestamp::Timestamp::as_millisecond);
        match text(&payload["type"]) {
            "message" => self.message(payload, id, timestamp)?,
            "reasoning" => {
                if let Some(part) = reasoning_part(payload, timestamp) {
                    self.assistant(id, timestamp, vec![part], true);
                }
            }
            "function_call" => self.tool_call(payload, timestamp, false, zh),
            "custom_tool_call" => self.tool_call(payload, timestamp, true, zh),
            "web_search_call" => self.push_tool(
                "web_search".into(),
                text(&payload["call_id"]).trim().into(),
                payload["action"].clone(),
                "completed",
                timestamp,
            ),
            "tool_search_call" => self.push_tool(
                "tool_search".into(),
                text(&payload["call_id"]).trim().into(),
                payload["arguments"].clone(),
                "running",
                timestamp,
            ),
            "image_generation_call" => self.push_tool(
                "image_generation".into(),
                text(&payload["call_id"]).trim().into(),
                json!({"revised_prompt": payload["revised_prompt"]}),
                "completed",
                timestamp,
            ),
            "tool_search_output" => {
                self.tool_search_output(payload, timestamp)?;
            }
            "function_call_output" => {
                self.tool_output(payload, timestamp, false)?;
            }
            "custom_tool_call_output" => {
                self.tool_output(payload, timestamp, true)?;
            }
            _ => (),
        }
        Ok(())
    }

    fn message(
        &mut self,
        payload: &Value,
        id: String,
        timestamp: i64,
    ) -> crate::Result<()> {
        let role = payload.get("role").map_or_else(|| "unknown".into(), string);
        if matches!(role.as_str(), "developer" | "system") {
            return Ok(());
        }
        let parts = content_parts(payload, timestamp)?;
        if parts.is_empty()
            || (role == "user"
                && context(
                    &payload["content"],
                    &user_text(&payload["content"]),
                ))
        {
            return Ok(());
        }
        if role == "assistant" {
            self.finish_plan("fail", None);
            let planned =
                parts.iter().any(|part| matches!(part, Part::Plan(_)));
            self.assistant(id, timestamp, parts, false);
            self.latest_assistant_text = self.current_assistant;
            if let Some(index) = self.current_assistant
                && self.assistant_fold.has_plan(&self.messages, index)
            {
                let parts = &self.messages[index].parts;
                let plan = parts
                    .iter()
                    .rposition(|part| matches!(part, Part::Plan(_)))
                    .filter(|_| planned)
                    .unwrap_or(parts.len() - 1);
                self.pending_plan = Some((index, plan));
                self.latest_assistant_text = None;
            }
            return Ok(());
        }
        let user_text = parts
            .iter()
            .filter_map(|part| match part {
                Part::Text(text) if !text.text.trim().is_empty() => {
                    Some(text.text.trim())
                }
                _ => None,
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        let is_notification = user_text.starts_with("<subagent_notification>")
            && user_text.ends_with("</subagent_notification>");
        if self.pending_plan.is_some()
            && role == "user"
            && !user_text.is_empty()
            && !is_notification
        {
            if user_text
                .trim_start()
                .starts_with("PLEASE IMPLEMENT THIS PLAN")
                || user_text == "Implement the plan."
            {
                self.finish_plan("success", None);
            } else {
                self.finish_plan("fail", Some(user_text));
            }
        } else {
            let notification = (role == "user")
                .then(|| {
                    subagent_notification(
                        &id,
                        timestamp,
                        &parts,
                        &mut self.nicknames,
                    )
                })
                .flatten();
            self.messages.push(
                notification.unwrap_or_else(|| {
                    Message::new(id, &role, timestamp, parts)
                }),
            );
        }
        self.current_assistant = None;
        self.latest_assistant_text = None;
        Ok(())
    }

    fn model(&self) -> Option<Value> {
        self.model.clone().map(Value::String)
    }

    fn assistant(
        &mut self,
        id: String,
        timestamp: i64,
        mut parts: Vec<Part>,
        reasoning: bool,
    ) {
        if let Some(index) = self.assistant_fold.fold(
            &mut self.messages,
            self.current_assistant,
            &mut parts,
            reasoning,
        ) {
            if self.messages[index].model.is_none() {
                self.messages[index].model = self.model();
            }
            return;
        }
        if !reasoning
            && self.messages.last().is_some_and(|message| {
                message.role == "assistant"
                    && message.time_created == timestamp
                    && message.parts == parts
            })
        {
            self.current_assistant = Some(self.messages.len() - 1);
            return;
        }
        let mut message = Message::new(id, "assistant", timestamp, parts);
        message.agent = Some("codex".into());
        message.model = self.model();
        self.messages.push(message);
        self.current_assistant = Some(self.messages.len() - 1);
    }

    fn finish_plan(&mut self, status: &str, output: Option<String>) {
        if let Some((message, part)) = self.pending_plan.take()
            && let Part::Plan(plan) = &mut self.messages[message].parts[part]
        {
            plan.approval_status = status.into();
            plan.output = output.into();
        }
    }

    fn tool_call(
        &mut self,
        payload: &Value,
        timestamp: i64,
        custom: bool,
        zh: bool,
    ) {
        let name = text(&payload["name"]).trim();
        if name.is_empty() {
            return;
        }
        let call_id = text(&payload["call_id"]).trim().to_owned();
        let calls = if custom && name == "exec" {
            exec::decode(&payload["input"])
        } else {
            Vec::new()
        };
        if calls.is_empty() {
            let arguments = if custom {
                if name == "apply_patch" {
                    let input = &payload["input"];
                    crate::providers::codex::patch::parse(
                        &if truthy(input) {
                            string(input)
                        } else {
                            String::new()
                        },
                        zh,
                    )
                } else {
                    payload["input"].clone()
                }
            } else {
                let arguments = payload
                    .get("arguments")
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                parsed_string(&arguments).unwrap_or(arguments)
            };
            let namespace = text(&payload["namespace"]).trim();
            self.push_tool(
                tool_name(name, namespace),
                call_id,
                arguments,
                "running",
                timestamp,
            );
            return;
        }
        let target = exec::output_target(&calls);
        for (index, call) in calls.into_iter().enumerate() {
            let (name, namespace) = exec::split_tool_name(&call.name);
            let arguments = if name == "apply_patch" {
                crate::providers::codex::patch::parse(
                    exec::patch_text(&call.args),
                    zh,
                )
            } else {
                call.args.clone()
            };
            let id = if Some(index) == target {
                call_id.clone()
            } else {
                format!("{call_id}#{index}")
            };
            self.push_tool(
                tool_name(name, namespace),
                id,
                arguments,
                "running",
                timestamp,
            );
        }
    }

    fn push_tool(
        &mut self,
        tool: String,
        call_id: String,
        arguments: Value,
        status: &str,
        timestamp: i64,
    ) {
        let part = Part::Tool(Box::new(ToolPart {
            subagent_type: None,
            title: tool.clone(),
            tool,
            call_id: call_id.clone(),
            state: serde_json::Map::from_iter([
                ("status".into(), status.into()),
                ("arguments".into(), arguments),
            ]),
            time_created: timestamp,
            nickname: None,
            subagent_id: None,
        }));
        let location = if let Some(index) = self.latest_assistant_text {
            self.messages[index].parts.push(part);
            (index, self.messages[index].parts.len() - 1)
        } else {
            let mut message = Message::new(
                timestamp.to_string(),
                "assistant",
                timestamp,
                vec![part],
            );
            message.mode = Some("tool".into());
            message.model = self.model();
            self.messages.push(message);
            self.current_assistant = Some(self.messages.len() - 1);
            (self.messages.len() - 1, 0)
        };
        if !call_id.is_empty() {
            self.pending_calls.insert(call_id, location);
        }
    }

    fn running_tool(&mut self, call_id: &str) -> Option<&mut ToolPart> {
        let &(message, part) = self.pending_calls.get(call_id)?;
        match &mut self.messages[message].parts[part] {
            Part::Tool(tool) if tool.state["status"] == "running" => Some(tool),
            _ => None,
        }
    }

    fn tool_search_output(
        &mut self,
        payload: &Value,
        timestamp: i64,
    ) -> crate::Result<()> {
        let output = serde_json::to_value([Part::text(
            tool_search_text(payload),
            timestamp,
        )])?;
        if let Some(tool) = self.running_tool(text(&payload["call_id"]).trim())
        {
            tool.state.insert("status".into(), "completed".into());
            tool.state.insert("output".into(), output);
        }
        Ok(())
    }

    fn tool_output(
        &mut self,
        payload: &Value,
        timestamp: i64,
        custom: bool,
    ) -> crate::Result<()> {
        let call_id = text(&payload["call_id"]).trim();
        let raw = &payload["output"];
        let (parts, status) = output_parts(raw, timestamp, custom);
        let updates = json!({"status": status}).as_object().cloned();
        if let Some(tool) = crate::session::assembly::backfill(
            &mut self.messages,
            &self.pending_calls,
            call_id,
            &parts,
            updates,
        )? {
            let output = serde_json::to_value(&parts)?;
            record_subagent_output(tool, raw, &output, &mut self.nicknames);
        }
        Ok(())
    }
}

pub fn read(
    session: &Session,
    zh: bool,
    subagents: &[PathBuf],
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    let mut decoder = Decoder::default();
    rollout::scan(&session.source_path, diagnostics, |record, diagnostics| {
        if let Err(error) = decoder.record(&record, zh) {
            diagnostics(RecoverableDiagnostic::MessageConvertFailed(
                error.to_string(),
            ))?;
        }
        Ok(())
    })?;
    decoder.finish_plan("fail", None);
    crate::providers::text::clean_messages(&mut decoder.messages);
    let mut totals = decoder
        .usage
        .as_ref()
        .map(Usage::totals)
        .unwrap_or_default();
    children::merge(
        subagents,
        &mut decoder.messages,
        &mut totals,
        diagnostics,
    )?;
    let mut stats = Stats::default();
    stats.add_tokens(&totals.input.into(), &totals.output.into())?;
    if totals.cache_read > 0 {
        stats
            .extra
            .insert("total_cache_read_tokens".into(), totals.cache_read.into());
    }
    stats.message_count = decoder.messages.len();
    let mut data = session.payload(decoder.messages, stats);
    data.directory = session.source_metadata["cwd"].clone();
    Ok(data)
}
