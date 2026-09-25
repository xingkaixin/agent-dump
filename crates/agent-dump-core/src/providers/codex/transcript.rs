use crate::compat::value::text;
use crate::compat::value::{field, parsed_string, string, truthy};
use crate::providers::codex::enrichment::{
    injected_context, inner_tag, output_parts, record_subagent_output,
    subagent_notification,
};
use crate::providers::contract::RecoverableDiagnostic;
use crate::providers::jsonl;
use crate::session::{
    Message, Part, PlanPart, Session, SessionData, Stats, TextPart, ToolPart,
    parse_timestamp,
};
use serde_json::{Value, json};
use std::collections::HashMap;

#[derive(Default)]
struct Decoder {
    messages: Vec<Message>,
    pending_calls: HashMap<String, (usize, usize)>,
    nicknames: HashMap<String, String>,
    current_assistant: Option<usize>,
    latest_assistant_text: Option<usize>,
    pending_plan: Option<(usize, usize)>,
}

fn content_parts(
    payload: &Value,
    timestamp: i64,
    reasoning: bool,
) -> crate::Result<Vec<Part>> {
    let key = if reasoning { "summary" } else { "content" };
    let expected = if reasoning {
        "summary_text"
    } else if payload["role"] == "assistant" {
        "output_text"
    } else {
        "input_text"
    };
    let Some(items) = payload[key].as_array() else {
        return Ok(Vec::new());
    };
    let mut parts = Vec::new();
    for item in items {
        if !reasoning
            && matches!(item["type"], Value::Array(_) | Value::Object(_))
        {
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
        if reasoning {
            parts.push(Part::Reasoning(TextPart {
                text: body,
                time_created: timestamp,
            }));
            continue;
        }
        if payload["role"] == "assistant"
            && let Some(plan) = inner_tag(&body, "proposed_plan")
                .filter(|plan| !plan.is_empty())
        {
            parts.push(Part::Plan(PlanPart {
                input: plan.into(),
                output: Value::Null,
                approval_status: "fail".into(),
                time_created: timestamp,
            }));
            continue;
        }
        parts.push(Part::text(body, timestamp));
    }
    Ok(parts)
}

impl Decoder {
    fn record(&mut self, record: &Value, zh: bool) -> crate::Result<()> {
        let payload = &record["payload"];
        if record["type"] != "response_item" || !payload.is_object() {
            return Ok(());
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
                let parts = content_parts(payload, timestamp, true)?;
                self.assistant(id, timestamp, parts, true);
            }
            "function_call" => self.tool_call(payload, timestamp, false, zh),
            "custom_tool_call" => self.tool_call(payload, timestamp, true, zh),
            "function_call_output" => {
                self.tool_output(payload, id, timestamp, false)?;
            }
            "custom_tool_call_output" => {
                self.tool_output(payload, id, timestamp, true)?;
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
        let parts = content_parts(payload, timestamp, false)?;
        if parts.is_empty() {
            return Ok(());
        }
        let role = payload.get("role").map_or_else(|| "unknown".into(), string);
        let role = if role == "user" && injected_context(&payload["content"]) {
            "developer"
        } else {
            &role
        };
        if role == "assistant" {
            self.finish_plan("fail", None);
            self.assistant(id, timestamp, parts, false);
            self.latest_assistant_text = self.current_assistant;
            if let Some(index) = self.current_assistant
                && self.messages[index]
                    .parts
                    .iter()
                    .any(|part| matches!(part, Part::Plan(_)))
            {
                self.pending_plan =
                    Some((index, self.messages[index].parts.len() - 1));
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
        if self.pending_plan.is_some()
            && role == "user"
            && !user_text.is_empty()
        {
            if user_text
                .trim_start()
                .starts_with("PLEASE IMPLEMENT THIS PLAN")
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
                    Message::new(id, role, timestamp, parts)
                }),
            );
        }
        self.current_assistant = None;
        self.latest_assistant_text = None;
        Ok(())
    }

    fn assistant(
        &mut self,
        id: String,
        timestamp: i64,
        mut parts: Vec<Part>,
        reasoning: bool,
    ) {
        if parts.is_empty() {
            return;
        }
        if crate::session::assembly::fold_assistant(
            &mut self.messages,
            self.current_assistant,
            &mut parts,
            reasoning,
        )
        .is_some()
        {
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
        let name = field(payload, "name");
        let normalized = match (custom, name.as_str()) {
            (false, "spawn_agent") => "subagent",
            (true, "apply_patch") => "patch",
            _ => &name,
        };
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
        let call_id = field(payload, "call_id");
        let title = match normalized {
            "exec_command" => "bash",
            "apply_patch" => "patch",
            _ => normalized,
        };
        let part = Part::Tool(Box::new(ToolPart {
            subagent_type: None,
            tool: normalized.into(),
            call_id: call_id.clone(),
            title: title.into(),
            state: json!({"arguments": arguments}).as_object().unwrap().clone(),
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
            self.messages.push(message);
            self.current_assistant = Some(self.messages.len() - 1);
            (self.messages.len() - 1, 0)
        };
        if !call_id.is_empty() {
            self.pending_calls.insert(call_id, location);
        }
    }

    fn tool_output(
        &mut self,
        payload: &Value,
        id: String,
        timestamp: i64,
        custom: bool,
    ) -> crate::Result<()> {
        let call_id = field(payload, "call_id");
        let raw = &payload["output"];
        let parts = output_parts(raw, timestamp, custom);
        if parts.is_empty() {
            return Ok(());
        }
        if let Some(tool) = crate::session::assembly::backfill(
            &mut self.messages,
            &self.pending_calls,
            &call_id,
            &parts,
            None,
        )? {
            let output = serde_json::to_value(&parts)?;
            record_subagent_output(tool, raw, &output, &mut self.nicknames);
            return Ok(());
        }
        let mut message = Message::new(id, "tool", timestamp, parts);
        message.tool_call_id = (!call_id.is_empty()).then_some(call_id);
        self.messages.push(message);
        Ok(())
    }
}

pub fn read(
    session: &Session,
    zh: bool,
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<SessionData> {
    let mut decoder = Decoder::default();
    let mut stats = Stats::default();
    jsonl::scan(&session.source_path, diagnostics, |record, diagnostics| {
        let result = decoder.record(&record, zh).and_then(|()| {
            let usage = &record["payload"]["info"]["total_token_usage"];
            stats.add_tokens(&usage["input_tokens"], &usage["output_tokens"])
        });
        if let Err(error) = result {
            diagnostics(RecoverableDiagnostic::MessageConvertFailed(
                error.to_string(),
            ))?;
        }
        Ok(())
    })?;
    decoder.finish_plan("fail", None);
    stats.message_count = decoder.messages.len();
    let mut data = session.payload(decoder.messages, stats);
    data.directory = session.source_metadata["cwd"].clone();
    Ok(data)
}
