use crate::compat::value::{integer, text};
use crate::providers::dsh::log::{Log, is_integer, is_packed};
use crate::providers::text::clean;
use crate::session::{ImagePart, Message, Part, TextPart, ToolPart};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{HashMap, HashSet};
use std::fmt::Write as _;
use std::path::Path;

const UNAVAILABLE: &str = "Image attachment unavailable";

pub struct Transcript {
    pub messages: Vec<Message>,
    pub title: Option<String>,
    pub model: Option<String>,
    pub updated: i64,
    pub input: i64,
    pub output: i64,
}

pub fn title(value: &str) -> Option<String> {
    clean(value)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(crate::providers::title::normalize_title)
}

fn nonempty(value: &Value) -> Option<String> {
    Some(text(value))
        .filter(|text| !text.is_empty())
        .map(str::to_owned)
}

#[allow(
    clippy::cast_possible_truncation,
    reason = "Token counts are whole numbers; negative or non-finite ones count as zero"
)]
fn positive(value: &Value) -> i64 {
    value
        .as_f64()
        .filter(|n| n.is_finite() && *n > 0.0)
        .map_or(0, |n| n as i64)
}

fn text_part(reasoning: bool, value: &str, time: i64) -> Option<Part> {
    let body = clean(value);
    if body.is_empty() {
        return None;
    }
    Some(if reasoning {
        Part::Reasoning(TextPart {
            text: body,
            time_created: time,
        })
    } else {
        Part::text(body, time)
    })
}

fn tool(id: &str, name: &str, arguments: &Value, time: i64) -> Part {
    let name = Some(name.trim()).filter(|name| !name.is_empty());
    let name = name.unwrap_or("tool");
    let input = match arguments {
        Value::String(raw) => {
            serde_json::from_str(raw).unwrap_or_else(|_| arguments.clone())
        }
        Value::Null => json!({}),
        _ => arguments.clone(),
    };
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: id.into(),
        title: name.to_lowercase(),
        state: Map::from_iter([
            ("status".into(), "running".into()),
            ("input".into(), input),
            ("output".into(), Value::Null),
        ]),
        time_created: time,
        nickname: None,
        subagent_id: None,
    }))
}

fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] =
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let block = chunk
            .iter()
            .zip([16, 8, 0])
            .fold(0_u32, |block, (byte, shift)| {
                block | u32::from(*byte) << shift
            });
        for index in 0..4 {
            if index <= chunk.len() {
                let sextet = (block >> (18 - 6 * index)) & 63;
                out.push(char::from(ALPHABET[sextet as usize]));
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// Loads an image from DSH's content-addressed store after checking that its
/// bytes still match the recorded digest and size.
fn image(block: &Value, time: i64, attachments: &Path) -> Option<Part> {
    let attachment = &block["attachment"];
    let mime = text(&attachment["mediaType"]);
    let digest = text(&attachment["attachmentId"])
        .strip_prefix("sha256:")
        .filter(|digest| {
            digest.len() == 64
                && digest
                    .bytes()
                    .all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f'))
        })?;
    if !["image/png", "image/jpeg", "image/webp", "image/gif"].contains(&mime) {
        return None;
    }
    let path = attachments.join("objects").join(&digest[..2]).join(digest);
    let bytes = crate::storage::source_io::read(&path).ok()?;
    let mut actual = String::new();
    for byte in Sha256::digest(&bytes) {
        write!(actual, "{byte:02x}").ok()?;
    }
    let size = &attachment["bytes"];
    let resized =
        size.is_number() && size.as_u64() != u64::try_from(bytes.len()).ok();
    if actual != digest || resized {
        return None;
    }
    Some(Part::Image(ImagePart {
        mime_type: Some(mime.into()),
        data: base64(&bytes).into(),
        time_created: time,
    }))
}

/// `Some(true)` appends to the visible conversation and `Some(false)`
/// replaces a range of it; any other operation makes the log invalid.
fn appends(event: &Value) -> Option<bool> {
    let operation = &event["surfaceOp"];
    if operation == "append" {
        return Some(true);
    }
    let replaces = operation["op"] == "replace"
        && is_integer(&operation["start"])
        && is_integer(&operation["end"]);
    replaces.then_some(false)
}

/// Identifies a model step by its turn and step numbers, compared bit for bit.
fn step(data: &Value) -> Option<(u64, u64)> {
    let turn = data["turn"].as_f64()?;
    let step = data["step"].as_f64()?;
    Some((turn.to_bits(), step.to_bits()))
}

enum Block {
    Text {
        reasoning: bool,
        text: String,
    },
    Tool {
        id: String,
        name: String,
        arguments: Value,
    },
}

/// One streamed change to the block at an index of a model step.
enum Delta<'a> {
    Text {
        reasoning: bool,
        text: &'a str,
    },
    Tool {
        id: &'a str,
        name: &'a str,
        arguments: &'a str,
    },
    End(&'a Value),
}

fn apply(blocks: &mut Vec<(f64, Block)>, index: f64, delta: Delta<'_>) {
    let position = blocks
        .iter()
        .position(|(key, _)| key.to_bits() == index.to_bits());
    let old = position.map(|position| &mut blocks[position].1);
    let block = match (delta, old) {
        (
            Delta::Text { reasoning, text },
            Some(Block::Text {
                reasoning: same,
                text: previous,
            }),
        ) if *same == reasoning => {
            previous.push_str(text);
            return;
        }
        (Delta::Text { reasoning, text }, _) => Block::Text {
            reasoning,
            text: text.into(),
        },
        (
            Delta::Tool {
                id,
                name,
                arguments,
            },
            Some(Block::Tool {
                id: previous_id,
                name: previous_name,
                arguments: previous,
            }),
        ) => {
            *previous_id = id.into();
            if !name.is_empty() {
                *previous_name = name.into();
            }
            match previous {
                Value::String(previous) => previous.push_str(arguments),
                previous => *previous = arguments.into(),
            }
            return;
        }
        (
            Delta::Tool {
                id,
                name,
                arguments,
            },
            _,
        ) => Block::Tool {
            id: id.into(),
            name: name.into(),
            arguments: arguments.into(),
        },
        (Delta::End(block), _) => match text(&block["type"]) {
            "tool-call" => Block::Tool {
                id: text(&block["id"]).into(),
                name: text(&block["name"]).into(),
                arguments: block["arguments"].clone(),
            },
            kind => Block::Text {
                reasoning: kind == "reasoning",
                text: text(&block["text"]).into(),
            },
        },
    };
    match position {
        Some(position) => blocks[position].1 = block,
        None => blocks.push((index, block)),
    }
}

struct Pending {
    step: (u64, u64),
    first: i64,
    last: i64,
    blocks: Vec<(f64, Block)>,
    usage: Value,
}

struct Projector<'a> {
    attachments: Option<&'a Path>,
    canonical: HashSet<String>,
    messages: Vec<Message>,
    current: Option<usize>,
    tools: HashMap<String, (usize, usize)>,
    pending: Option<Pending>,
    settled: HashSet<(u64, u64)>,
    provider: Option<String>,
    model: Option<String>,
    input: i64,
    output: i64,
    own_title: Option<String>,
    inherited_title: Option<String>,
    label: Option<String>,
    human: Option<String>,
    updated: i64,
}

impl Projector<'_> {
    fn content(&self, raw: &Value, time: i64) -> Vec<Part> {
        let mut parts = Vec::new();
        let mut dropped = false;
        for block in raw.as_array().into_iter().flatten() {
            match text(&block["type"]) {
                kind @ ("text" | "reasoning") => {
                    let body = text(&block["text"]);
                    parts.extend(text_part(kind == "reasoning", body, time));
                }
                "tool-call" if !self.canonical.contains(text(&block["id"])) => {
                    parts.push(tool(
                        text(&block["id"]),
                        text(&block["name"]),
                        &block["arguments"],
                        time,
                    ));
                }
                "image" => {
                    match self
                        .attachments
                        .and_then(|attachments| image(block, time, attachments))
                    {
                        Some(image) => parts.push(image),
                        None => dropped = true,
                    }
                }
                _ => {}
            }
        }
        if parts.is_empty() && dropped {
            parts.push(Part::text(UNAVAILABLE.into(), time));
        }
        parts
    }

    fn push(&mut self, message: Message) {
        let index = self.messages.len();
        self.current = (message.role == "assistant").then_some(index);
        for (position, part) in message.parts.iter().enumerate() {
            if let Part::Tool(tool) = part
                && !tool.call_id.is_empty()
            {
                self.tools.insert(tool.call_id.clone(), (index, position));
            }
        }
        self.messages.push(message);
    }

    fn assistant(
        &mut self,
        id: String,
        time: i64,
        parts: Vec<Part>,
        provider: Option<String>,
        model: Option<String>,
        usage: &Value,
    ) {
        let mut message = Message::new(id, "assistant", time, parts);
        message.agent = Some("dsh".into());
        message.provider = provider;
        message.model = model.map(Value::String);
        if usage.is_object() {
            let read = positive(&usage["cacheReadTokens"]);
            let write = positive(&usage["cacheWriteTokens"]);
            let input = positive(&usage["inputTokens"])
                .saturating_add(read)
                .saturating_add(write);
            let output = positive(&usage["outputTokens"]);
            let reasoning = positive(&usage["reasoningTokens"]).min(output);
            if let Value::Object(tokens) = json!({
                "input": input,
                "output": output - reasoning,
                "reasoning": reasoning,
                "cache": {"read": read, "write": write}
            }) {
                message.tokens = tokens;
            }
            self.input = self.input.saturating_add(input);
            self.output = self.output.saturating_add(output);
        }
        if !message.parts.is_empty() {
            self.push(message);
        }
    }

    fn flush(&mut self) {
        let Some(mut pending) = self.pending.take() else {
            return;
        };
        pending.blocks.sort_by(|a, b| a.0.total_cmp(&b.0));
        let mut parts = Vec::new();
        for (_, block) in &pending.blocks {
            match block {
                Block::Tool {
                    id,
                    name,
                    arguments,
                } => {
                    if !self.canonical.contains(id) {
                        parts.push(tool(id, name, arguments, pending.last));
                    }
                }
                Block::Text { reasoning, text } => {
                    parts.extend(text_part(*reasoning, text, pending.first));
                }
            }
        }
        if !parts.is_empty() {
            self.assistant(
                format!(
                    "dsh-step-{}-{}",
                    f64::from_bits(pending.step.0),
                    f64::from_bits(pending.step.1)
                ),
                pending.first,
                parts,
                self.provider.clone(),
                self.model.clone(),
                &pending.usage,
            );
        }
    }

    /// The pending step a chunk at `time` adds to, unless the step's final
    /// message has already settled it.
    fn open(&mut self, step: (u64, u64), time: i64) -> Option<&mut Pending> {
        if self.settled.contains(&step) {
            return None;
        }
        if self
            .pending
            .as_ref()
            .is_some_and(|pending| pending.step != step)
        {
            self.flush();
        }
        let pending = self.pending.get_or_insert_with(|| Pending {
            step,
            first: time,
            last: time,
            blocks: Vec::new(),
            usage: Value::Null,
        });
        pending.last = time;
        Some(pending)
    }

    fn chunk(&mut self, data: &Value, time: i64) {
        let Some(pending) = step(data).and_then(|step| self.open(step, time))
        else {
            return;
        };
        let chunk = &data["chunk"];
        let Some(index) = chunk["index"].as_f64() else {
            if chunk["type"] == "usage" {
                pending.usage = chunk["usage"].clone();
            }
            return;
        };
        let delta = match text(&chunk["type"]) {
            kind @ ("text-delta" | "reasoning-delta") => Delta::Text {
                reasoning: kind == "reasoning-delta",
                text: text(&chunk["text"]),
            },
            "tool-call-delta" => Delta::Tool {
                id: text(&chunk["id"]),
                name: text(&chunk["name"]),
                arguments: text(&chunk["argumentsDelta"]),
            },
            "block-end"
                if ["text", "reasoning", "tool-call"]
                    .contains(&text(&chunk["block"]["type"])) =>
            {
                Delta::End(&chunk["block"])
            }
            _ => return,
        };
        apply(&mut pending.blocks, index, delta);
    }

    /// Replays a packed run of streamed chunks as one chunk each.
    fn packed(&mut self, row: &Value, seed: i64) {
        let data = &row["data"];
        let (Some(step), Some(index)) = (step(data), data["index"].as_f64())
        else {
            return;
        };
        let tool = row["type"] == "tool-call-chunks";
        let reasoning = row["type"] == "reasoning-chunks";
        let members = data[if tool { "args" } else { "texts" }]
            .as_array()
            .map_or(&[][..], Vec::as_slice);
        let mut time = integer(&row["time0"]);
        let sequence = integer(&row["seq0"])..;
        for ((position, member), seq) in
            members.iter().enumerate().zip(sequence)
        {
            if position > 0 {
                time = time.saturating_add(integer(&data["dt"][position - 1]));
            }
            if seq < seed {
                continue;
            }
            self.updated = self.updated.max(time);
            let delta = if tool {
                Delta::Tool {
                    id: text(&data["id"]),
                    name: text(&data["name"]),
                    arguments: text(member),
                }
            } else {
                Delta::Text {
                    reasoning,
                    text: text(member),
                }
            };
            if let Some(pending) = self.open(step, time) {
                apply(&mut pending.blocks, index, delta);
            }
        }
    }

    fn user(&mut self, event: &Value, own: bool) -> Option<()> {
        let data = &event["data"];
        let time = integer(&event["time"]);
        if !appends(event)? || !own || data["source"]["kind"] != "user" {
            return Some(());
        }
        let parts = self.content(&data["content"], time);
        if parts.is_empty() {
            return Some(());
        }
        let id = nonempty(&data["id"])
            .unwrap_or_else(|| format!("dsh-user-{}", integer(&event["seq"])));
        self.push(Message::new(id, "user", time, parts));
        if self.human.is_none() {
            self.human = data["content"]
                .as_array()
                .into_iter()
                .flatten()
                .filter(|block| block["type"] == "text")
                .map(|block| clean(text(&block["text"])))
                .find(|text| !text.is_empty());
        }
        Some(())
    }

    fn answer(&mut self, event: &Value, own: bool) -> Option<()> {
        let data = &event["data"];
        let visible = appends(event)?;
        if let Some(step) = step(data) {
            self.settled.insert(step);
            if self
                .pending
                .as_ref()
                .is_some_and(|pending| pending.step == step)
            {
                self.pending = None;
            }
        }
        if !visible || !own {
            return Some(());
        }
        let message = &data["message"];
        let provider = nonempty(&message["source"]["provider"]);
        let model = nonempty(&message["source"]["model"]);
        if provider.is_some() {
            self.provider.clone_from(&provider);
        }
        if model.is_some() {
            self.model.clone_from(&model);
        }
        let time = integer(&event["time"]);
        let id = nonempty(&message["id"]).unwrap_or_else(|| {
            format!("dsh-assistant-{}", integer(&event["seq"]))
        });
        let parts = self.content(&message["content"], time);
        self.assistant(id, time, parts, provider, model, &data["usage"]);
        Some(())
    }

    fn call(&mut self, event: &Value) {
        let data = &event["data"];
        let time = integer(&event["time"]);
        let id = text(&data["callId"]);
        let part = tool(id, text(&data["name"]), &data["arguments"], time);
        if let Some(current) = self.current {
            let position = self.messages[current].parts.len();
            self.messages[current].parts.push(part);
            self.tools.insert(id.into(), (current, position));
        } else {
            let mut message =
                Message::new(id.into(), "assistant", time, vec![part]);
            message.agent = Some("dsh".into());
            self.push(message);
        }
    }

    fn result(&mut self, event: &Value, own: bool) -> Option<()> {
        if !appends(event)? || !own {
            return Some(());
        }
        let data = &event["data"];
        let message = &data["message"];
        let id = text(&message["source"]["callId"]);
        let [block] = message["content"].as_array()?.as_slice() else {
            return None;
        };
        if message["source"]["kind"] != "tool"
            || block["type"] != "tool-result"
            || text(&block["toolCallId"]) != id
        {
            return None;
        }
        let output = self.content(&block["content"], integer(&event["time"]));
        let Some((message, part)) = self.tools.remove(id) else {
            return Some(());
        };
        let Part::Tool(tool) = &mut self.messages[message].parts[part] else {
            return Some(());
        };
        let error = block["isError"] == true || data["error"].is_object();
        let state = &mut tool.state;
        state.insert("output".into(), serde_json::to_value(output).ok()?);
        state.insert(
            "status".into(),
            if error { "error" } else { "completed" }.into(),
        );
        if let Some(meta) = data.get("meta") {
            state.insert("metadata".into(), meta.clone());
        }
        Some(())
    }

    fn consume(&mut self, event: &Value, own: bool) -> Option<()> {
        let data = &event["data"];
        match text(&event["type"]) {
            "user/message" => self.user(event, own)?,
            "assistant/message" => self.answer(event, own)?,
            "tool/call" if own => self.call(event),
            "tool/result" => self.result(event, own)?,
            "assistant/chunk" if own => {
                self.chunk(data, integer(&event["time"]));
            }
            "request/context" => {
                if let Some(provider) = nonempty(&data["provider"]) {
                    self.provider = Some(provider);
                }
                if let Some(model) = nonempty(&data["model"]) {
                    self.model = Some(model);
                }
            }
            "session/title" => {
                if let Some(title) = title(text(&data["title"])) {
                    if own {
                        self.own_title = Some(title);
                    } else {
                        self.inherited_title = Some(title);
                    }
                }
            }
            "subagent/descriptor" if own && self.label.is_none() => {
                self.label = title(text(&data["label"]));
            }
            _ => {}
        }
        Some(())
    }
}

/// Events before this sequence number were copied from the parent session.
fn seed(log: &Log) -> i64 {
    let header = &log.header;
    if integer(&header["version"]) < 2 {
        integer(&header["seedLength"])
    } else if header["isSeeded"] == true {
        log.events
            .iter()
            .rfind(|event| {
                event["type"] == "session/end-seed"
                    && event["data"]["inherited"] == true
            })
            .map_or(0, |event| integer(&event["seq"]) + 1)
    } else {
        0
    }
}

/// Projects a log into messages, or `None` when its events are inconsistent.
/// Without `attachments`, images become unavailable placeholders.
pub fn project(log: &Log, attachments: Option<&Path>) -> Option<Transcript> {
    let mut canonical = HashSet::new();
    for event in &log.events {
        if event["type"] == "tool/call" {
            let id = text(&event["data"]["callId"]);
            if id.is_empty() || !canonical.insert(id.to_owned()) {
                return None;
            }
        }
    }
    let mut projector = Projector {
        attachments,
        canonical,
        messages: Vec::new(),
        current: None,
        tools: HashMap::new(),
        pending: None,
        settled: HashSet::new(),
        provider: None,
        model: None,
        input: 0,
        output: 0,
        own_title: None,
        inherited_title: None,
        label: None,
        human: None,
        updated: 0,
    };
    let seed = seed(log);
    for event in &log.events {
        if is_packed(event) {
            projector.packed(event, seed);
            continue;
        }
        let own = integer(&event["seq"]) >= seed;
        if own {
            projector.updated = projector.updated.max(integer(&event["time"]));
        }
        projector.consume(event, own)?;
    }
    projector.flush();
    let Projector {
        messages,
        model,
        input,
        output,
        own_title,
        inherited_title,
        label,
        human,
        updated,
        ..
    } = projector;
    Some(Transcript {
        messages,
        title: own_title.or(label).or(human).or(inherited_title),
        model,
        updated: if updated == 0 {
            integer(&log.header["createdAt"])
        } else {
            updated
        },
        input,
        output,
    })
}
