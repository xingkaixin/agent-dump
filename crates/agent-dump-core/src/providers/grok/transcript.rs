use crate::compat::value::text;
use crate::providers::kimi::title;
use crate::session::{
    ImagePart, Message, Part, PlanPart, Stats, TextPart, ToolPart,
};
use serde_json::{Map, Value};
use std::collections::HashMap;
use std::path::Path;

const XAI: &str = "_x.ai/session/update";
// JavaScript's Number.MAX_SAFE_INTEGER, the bound CodeSesh applies to counts.
const SAFE: i64 = 9_007_199_254_740_991;

pub struct Transcript {
    pub messages: Vec<Message>,
    pub stats: Stats,
    pub prompt: Option<String>,
    pub model: Option<String>,
}

struct Event<'a> {
    xai: bool,
    params: &'a Value,
    update: &'a Value,
    time: i64,
    inferred: bool,
}

struct Usage {
    tokens: Tokens,
    total: i64,
    cost: Option<f64>,
    models: Vec<String>,
}

#[derive(Default)]
struct Tokens {
    input: i64,
    output: i64,
    reasoning: i64,
    cache_read: i64,
    cache_write: i64,
}

impl Tokens {
    fn add_to(&self, tokens: &mut Map<String, Value>) {
        let put = |map: &mut Map<String, Value>, key: &str, value| {
            let total = map.get(key).and_then(Value::as_i64).unwrap_or(0);
            map.insert(key.into(), add(total, value).into());
        };
        put(tokens, "input", self.input);
        put(tokens, "output", self.output);
        if self.reasoning > 0 {
            put(tokens, "reasoning", self.reasoning);
        }
        if self.cache_read > 0 || self.cache_write > 0 {
            let cache = tokens
                .entry("cache")
                .or_insert_with(|| Value::Object(Map::new()));
            if let Some(cache) = cache.as_object_mut() {
                put(cache, "read", self.cache_read);
                put(cache, "write", self.cache_write);
            }
        }
    }
}

fn add(a: i64, b: i64) -> i64 {
    a.saturating_add(b).min(SAFE)
}

fn string(value: &Value) -> Option<String> {
    value
        .as_str()
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_owned)
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "Only integral values within the safe integer range are accepted"
)]
fn safe(value: &Value, limit: i64) -> Option<i64> {
    value
        .as_f64()
        .filter(|n| *n >= 0.0 && n.fract() == 0.0)
        .map(|n| n as i64)
        .filter(|n| *n <= limit)
}

fn count(value: &Value) -> i64 {
    safe(value, SAFE).unwrap_or(0)
}

fn prompt_index(value: &Value) -> Option<i64> {
    value
        .as_i64()
        .filter(|n| n.unsigned_abs() <= SAFE.unsigned_abs())
}

fn unpack(record: &Value, fallback: i64) -> Option<Event<'_>> {
    let params = record
        .get("params")
        .filter(|params| params.is_object())
        .unwrap_or(record);
    let update = params.get("update").filter(|update| update.is_object())?;
    let time = safe(&params["_meta"]["agentTimestampMs"], SAFE).or_else(|| {
        safe(&record["timestamp"], SAFE / 1000).map(|seconds| seconds * 1000)
    });
    Some(Event {
        xai: record["method"] == XAI,
        params,
        update,
        time: time.unwrap_or(fallback),
        inferred: time.is_none(),
    })
}

fn block_text(value: &Value) -> &str {
    if value["type"] == "text" {
        text(&value["text"])
    } else {
        text(&value["resource"]["text"])
    }
}

fn visible(value: &str) -> bool {
    !crate::providers::text::clean(value).is_empty()
}

fn part(value: &Value, time: i64) -> Option<Part> {
    if value["type"] == "image" {
        let nonempty = |value: &Value| {
            value
                .as_str()
                .filter(|text| !text.is_empty())
                .map(str::to_owned)
        };
        let url = nonempty(&value["uri"]).or_else(|| nonempty(&value["url"]));
        let mime_type = value["mimeType"]
            .as_str()
            .or_else(|| value["mime_type"].as_str())
            .map(str::to_owned);
        // ImagePart has no URL field, so a URL image keeps its URL in `data`.
        let data = nonempty(&value["data"])
            .filter(|_| mime_type.as_ref().is_some_and(|mime| !mime.is_empty()))
            .or(url);
        if let Some(data) = data {
            return Some(Part::Image(ImagePart {
                mime_type,
                data: data.into(),
                time_created: time,
            }));
        }
    }
    let body = block_text(value);
    visible(body).then(|| Part::text(body.into(), time))
}

fn plan(update: &Value, time: i64) -> Option<Part> {
    let entries = update["entries"]
        .as_array()?
        .iter()
        .filter_map(|entry| {
            let body = crate::providers::text::clean(text(&entry["content"]));
            (!body.is_empty()).then(|| (body, entry["status"] == "completed"))
        })
        .collect::<Vec<_>>();
    if entries.is_empty() {
        return None;
    }
    Some(Part::Plan(PlanPart {
        input: entries
            .iter()
            .map(|(body, done)| {
                format!("- [{}] {body}", if *done { "x" } else { " " })
            })
            .collect::<Vec<_>>()
            .join("\n"),
        output: Value::Null,
        approval_status: if entries.iter().all(|(_, done)| *done) {
            "success"
        } else {
            "fail"
        }
        .into(),
        time_created: time,
    }))
}

#[allow(
    clippy::cast_precision_loss,
    reason = "Ticks are bounded by the safe integer range"
)]
fn usage(update: &Value) -> Option<Usage> {
    let usage = update.get("usage").filter(|usage| usage.is_object())?;
    let input = count(&usage["inputTokens"]);
    let output = count(&usage["outputTokens"]);
    let total = count(&usage["totalTokens"]);
    let ticks = count(&usage["costUsdTicks"]);
    let cost = (usage["usageIsIncomplete"] != true
        && usage["costIsPartial"] != true
        && ticks > 0)
        .then(|| ticks as f64 / 10_000_000_000.0);
    let models = usage["modelUsage"]
        .as_object()
        .into_iter()
        .flatten()
        .filter(|(_, model)| {
            count(&model["totalTokens"]) > 0
                || add(
                    count(&model["inputTokens"]),
                    count(&model["outputTokens"]),
                ) > 0
        })
        .map(|(name, _)| name.clone())
        .collect();
    Some(Usage {
        tokens: Tokens {
            input,
            output,
            reasoning: count(&usage["reasoningTokens"]),
            cache_read: count(&usage["cachedReadTokens"]),
            cache_write: count(&usage["cacheCreationTokens"]),
        },
        total: if total > 0 { total } else { add(input, output) },
        cost,
        models,
    })
}

fn canonical(records: &[Value], fallback: i64) -> Vec<usize> {
    let mut surviving = Vec::new();
    let mut starts = Vec::new();
    let mut has_seen = false;
    let mut in_run = false;
    let mut current = None;
    for (index, record) in records.iter().enumerate() {
        let Some(event) = unpack(record, fallback) else {
            in_run = false;
            current = None;
            surviving.push(index);
            continue;
        };
        let kind = text(&event.update["sessionUpdate"]);
        if event.xai
            && kind == "rewind_marker"
            && let Some(target) = event.update["target_prompt_index"]
                .as_u64()
                .filter(|n| *n <= SAFE.unsigned_abs())
                .and_then(|n| usize::try_from(n).ok())
        {
            surviving.truncate(
                starts.get(target).copied().unwrap_or(surviving.len()),
            );
            starts.truncate(target);
            in_run = false;
            current = None;
            continue;
        }
        if !event.xai
            && kind == "user_message_chunk"
            && event.update["_meta"]["hostTurn"] != true
        {
            let prompt = event.update["_meta"]["promptIndex"]
                .as_i64()
                .filter(|n| (0..=SAFE).contains(n));
            if prompt.is_some() {
                has_seen = true;
            }
            let counted = !has_seen || prompt.is_some();
            let new = !in_run
                || ((has_seen || prompt.is_some()) && prompt != current);
            in_run = true;
            if new {
                current = prompt;
                if counted {
                    starts.push(surviving.len());
                }
            }
        } else {
            in_run = false;
            current = None;
        }
        surviving.push(index);
    }
    surviving
}

fn status(value: &Value) -> Option<&'static str> {
    match text(value).to_lowercase().as_str() {
        "completed" => Some("completed"),
        "failed" => Some("error"),
        "in_progress" | "pending" => Some("running"),
        _ => None,
    }
}

fn tool_title(name: &str) -> &str {
    match name {
        "get_command_or_subagent_output" => "task",
        "list_dir" => "list",
        "read_file" => "read",
        "run_terminal_command" => "bash",
        "search_replace" => "edit",
        "todo_write" => "todo",
        "web_fetch" => "web fetch",
        _ => name,
    }
}

fn output(update: &Value) -> Option<Value> {
    if let Some(output) = update.get("rawOutput").filter(|v| !v.is_null()) {
        return Some(output.clone());
    }
    let content = update["content"].as_array()?;
    let texts = content
        .iter()
        .map(|item| {
            block_text(if item["type"] == "content" {
                &item["content"]
            } else {
                item
            })
        })
        .filter(|text| !text.is_empty())
        .collect::<Vec<_>>();
    Some(if texts.is_empty() {
        Value::Array(content.clone())
    } else {
        texts.join("\n").into()
    })
}

fn tool(update: &Value, call: String, time: i64) -> Part {
    let native = &update["_meta"]["x.ai/tool"];
    let name = string(&native["name"])
        .or_else(|| string(&update["title"]))
        .unwrap_or_else(|| "tool".into());
    let mut metadata = Map::new();
    if let Some(kind) = native
        .get("kind")
        .filter(|kind| kind.is_string())
        .or_else(|| update.get("kind").filter(|kind| kind.is_string()))
    {
        metadata.insert("kind".into(), kind.clone());
    }
    if let Some(locations) = update.get("locations") {
        metadata.insert("locations".into(), locations.clone());
    }
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        title: tool_title(&name).into(),
        tool: name,
        call_id: call,
        state: Map::from_iter([
            (
                "status".into(),
                status(&update["status"]).unwrap_or("running").into(),
            ),
            (
                "input".into(),
                update.get("rawInput").cloned().unwrap_or_default(),
            ),
            ("output".into(), Value::Null),
            ("metadata".into(), metadata.into()),
        ]),
        time_created: time,
        nickname: None,
        subagent_id: None,
    }))
}

#[derive(Default)]
struct Builder {
    messages: Vec<Message>,
    prompt: Option<String>,
    model: Option<String>,
    mode: Option<String>,
    active: Option<usize>,
    user_prompt: Option<i64>,
    assistant_prompt: Option<String>,
    latest_plan: Option<(usize, usize)>,
    tools: HashMap<String, (usize, usize)>,
}

impl Builder {
    fn message(&mut self, role: &str, id: String, event: &Event) -> usize {
        let mut message = Message::new(id, role, event.time, Vec::new());
        message.inferred_time = event.inferred;
        if role == "assistant" {
            message.agent = Some("grok".into());
            message.provider = Some("xai".into());
            message.model = self.model.clone().map(Value::String);
            message.mode.clone_from(&self.mode);
        }
        self.messages.push(message);
        self.messages.len() - 1
    }

    fn active(&self, role: &str) -> Option<usize> {
        self.active
            .filter(|index| self.messages[*index].role == role)
    }

    fn xai(&mut self, kind: &str, update: &Value) {
        match kind {
            "model_changed" | "model_auto_switched" => {
                let key = if kind == "model_changed" {
                    "model_id"
                } else {
                    "new_model_id"
                };
                if let Some(model) = string(&update[key]) {
                    self.model = Some(model);
                }
            }
            "subagent_spawned" => {
                if let Some(index) = self.active("assistant")
                    && self.messages[index].subagent_id.is_none()
                {
                    self.messages[index].subagent_id =
                        string(&update["child_session_id"]);
                }
            }
            "turn_completed" => self.turn(update),
            _ => {}
        }
    }

    fn turn(&mut self, update: &Value) {
        let Some(usage) = usage(update) else {
            return;
        };
        let model = match usage.models.as_slice() {
            [model] => Some(model.clone()),
            _ => self.model.clone(),
        };
        let assistant = |message: &Message| message.role == "assistant";
        let Some(index) = self
            .messages
            .iter()
            .rposition(|message| {
                assistant(message) && message.tokens.is_empty()
            })
            .or_else(|| {
                self.messages.iter().rposition(|message| {
                    assistant(message)
                        && message.model.as_ref().and_then(Value::as_str)
                            == model.as_deref()
                })
            })
        else {
            return;
        };
        let message = &mut self.messages[index];
        if message.tokens.is_empty() {
            if message.model.is_none() {
                message.model = model.map(Value::String);
            }
            if let Some(cost) = usage.cost {
                message.cost = crate::compat::json::float(cost);
            }
        } else if let Some(cost) = usage.cost {
            message.cost = crate::compat::json::float(
                message.cost.as_f64().unwrap_or_default() + cost,
            );
        }
        usage.tokens.add_to(&mut message.tokens);
    }

    fn tool_update(&mut self, update: &Value) {
        let Some(&(index, position)) = string(&update["toolCallId"])
            .and_then(|call| self.tools.get(&call))
        else {
            return;
        };
        let Part::Tool(tool) = &mut self.messages[index].parts[position] else {
            return;
        };
        let status = status(&update["status"]);
        if let Some(status) = status {
            tool.state.insert("status".into(), status.into());
        }
        if let Some(input) = update.get("rawInput") {
            tool.state.insert("input".into(), input.clone());
        }
        if let Some(output) = output(update) {
            let key = if status == Some("error") {
                "error"
            } else {
                "output"
            };
            tool.state.insert(key.into(), output);
        }
        let metadata = tool
            .state
            .entry("metadata")
            .or_insert_with(|| Value::Object(Map::new()));
        if let Some(metadata) = metadata.as_object_mut() {
            for key in ["kind", "locations"] {
                if let Some(value) = update.get(key) {
                    metadata.insert(key.into(), value.clone());
                }
            }
        }
    }

    fn user(&mut self, session: &str, event: &Event) {
        let update = event.update;
        if update["_meta"]["hostTurn"] == true {
            return;
        }
        let Some(part) = part(&update["content"], event.time) else {
            return;
        };
        if self.prompt.is_none()
            && let Part::Text(part) = &part
        {
            self.prompt = title(&part.text);
        }
        let prompt = prompt_index(&update["_meta"]["promptIndex"]);
        let index = self
            .active("user")
            .filter(|_| {
                prompt.is_none()
                    || self.user_prompt.is_none()
                    || prompt == self.user_prompt
            })
            .unwrap_or_else(|| {
                let id = string(&event.params["_meta"]["eventId"])
                    .unwrap_or_else(|| {
                        format!("{session}-user-{}", event.time)
                    });
                self.message("user", id, event)
            });
        let parts = &mut self.messages[index].parts;
        match (parts.last_mut(), part) {
            (Some(Part::Text(last)), Part::Text(part)) => {
                last.text.push_str(&part.text);
            }
            (_, part) => parts.push(part),
        }
        self.active = Some(index);
        self.user_prompt = prompt;
        self.assistant_prompt = None;
        self.latest_plan = None;
    }

    fn assistant(&mut self, session: &str, kind: &str, event: &Event) {
        let update = event.update;
        let part = match kind {
            "agent_message_chunk" | "agent_thought_chunk" => {
                let body = block_text(&update["content"]);
                if !visible(body) {
                    return;
                }
                let body = TextPart {
                    text: body.into(),
                    time_created: event.time,
                };
                if kind == "agent_message_chunk" {
                    Part::Text(body)
                } else {
                    Part::Reasoning(body)
                }
            }
            "plan" => match plan(update, event.time) {
                Some(part) => part,
                None => return,
            },
            "tool_call" => match string(&update["toolCallId"]) {
                Some(call) => tool(update, call, event.time),
                None => return,
            },
            _ => return,
        };
        let meta = &event.params["_meta"];
        let prompt = string(&meta["promptId"]);
        let reuse = self.active("assistant").filter(|_| {
            !(prompt.is_some()
                && self.assistant_prompt.is_some()
                && prompt != self.assistant_prompt)
        });
        let index = reuse.unwrap_or_else(|| {
            self.latest_plan = None;
            let id = prompt
                .clone()
                .or_else(|| string(&meta["eventId"]))
                .unwrap_or_else(|| {
                    format!("{session}-assistant-{}", event.time)
                });
            self.message("assistant", id, event)
        });
        self.assistant_prompt =
            prompt.or_else(|| reuse.and_then(|_| self.assistant_prompt.take()));
        self.active = Some(index);
        self.user_prompt = None;
        if matches!(part, Part::Plan(_)) {
            if let Some((plan, position)) = self.latest_plan {
                self.messages[plan].parts[position] = part;
                return;
            }
            self.latest_plan = Some((index, self.messages[index].parts.len()));
        }
        let message = &mut self.messages[index];
        match (message.parts.last_mut(), &part) {
            (Some(Part::Text(last)), Part::Text(part))
            | (Some(Part::Reasoning(last)), Part::Reasoning(part)) => {
                last.text.push_str(&part.text);
                return;
            }
            _ => {}
        }
        if let Part::Tool(tool) = &part {
            self.tools
                .insert(tool.call_id.clone(), (index, message.parts.len()));
            message.mode = Some("tool".into());
        } else if message.mode.is_none() {
            message.mode.clone_from(&self.mode);
        }
        if message.model.is_none() {
            message.model = self.model.clone().map(Value::String);
        }
        message.parts.push(part);
    }
}

fn stats(records: &[Value], fallback: i64, messages: &[Message]) -> Stats {
    let mut tokens = Tokens::default();
    let mut total = 0;
    let mut cost = None;
    for record in records {
        let Some(event) = unpack(record, fallback) else {
            continue;
        };
        if !event.xai || event.update["sessionUpdate"] != "turn_completed" {
            continue;
        }
        let Some(usage) = usage(event.update) else {
            continue;
        };
        tokens.input = add(tokens.input, usage.tokens.input);
        tokens.output = add(tokens.output, usage.tokens.output);
        tokens.cache_read = add(tokens.cache_read, usage.tokens.cache_read);
        tokens.cache_write = add(tokens.cache_write, usage.tokens.cache_write);
        total = add(total, usage.total);
        if let Some(recorded) = usage.cost {
            *cost.get_or_insert(0.0) += recorded;
        }
    }
    let mut stats = Stats {
        message_count: messages.len(),
        total_input_tokens: tokens.input.into(),
        total_output_tokens: tokens.output.into(),
        total_tokens: Some(total.into()),
        ..Stats::default()
    };
    if let Some(cost) = cost {
        stats.total_cost = crate::compat::json::float(cost);
    }
    for (key, value) in [
        ("total_cache_read_tokens", tokens.cache_read),
        ("total_cache_create_tokens", tokens.cache_write),
    ] {
        if value > 0 {
            stats.extra.insert(key.into(), value.into());
        }
    }
    stats
}

pub fn read(
    path: &Path,
    session: &str,
    fallback: i64,
    model: Option<String>,
    diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
) -> crate::Result<Transcript> {
    let mut records = Vec::new();
    crate::providers::jsonl::scan(path, diagnostics, |record, _| {
        records.push(record);
        Ok(())
    })?;
    let mut builder = Builder {
        model,
        ..Builder::default()
    };
    for index in canonical(&records, fallback) {
        let Some(event) = unpack(&records[index], fallback) else {
            continue;
        };
        let kind = text(&event.update["sessionUpdate"]);
        if event.xai {
            builder.xai(kind, event.update);
            continue;
        }
        match kind {
            "current_mode_update" => {
                builder.mode = string(&event.update["currentModeId"]);
            }
            "tool_call_update" => builder.tool_update(event.update),
            "user_message_chunk" => builder.user(session, &event),
            _ => builder.assistant(session, kind, &event),
        }
    }
    let mut messages = builder.messages;
    crate::providers::text::clean_messages(&mut messages);
    Ok(Transcript {
        stats: stats(&records, fallback, &messages),
        messages,
        prompt: builder.prompt,
        model: builder.model,
    })
}
