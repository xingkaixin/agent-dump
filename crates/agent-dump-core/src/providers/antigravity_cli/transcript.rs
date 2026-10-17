use super::proto::{self, Message as _};
use crate::session::{Message, Part};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};

#[derive(Default)]
pub struct Transcript {
    pub messages: Vec<Message>,
    pub title: Option<String>,
    pub model: Option<String>,
    pub unsupported: usize,
    pub input: u64,
    pub output: u64,
    pub total: Option<u64>,
}

#[derive(Clone, Copy, Default)]
struct Tokens {
    input: u64,
    output: u64,
    reasoning: u64,
    cache_read: u64,
    cache_create: u64,
}

impl Tokens {
    fn new(usage: &proto::Usage) -> Option<Self> {
        let tokens = Self {
            input: usage
                .input
                .saturating_add(usage.cache_read)
                .saturating_add(usage.cache_create),
            output: usage
                .visible_output
                .max(usage.total_output.saturating_sub(usage.reasoning)),
            reasoning: usage.reasoning,
            cache_read: usage.cache_read,
            cache_create: usage.cache_create,
        };
        (tokens.input > 0 || tokens.output > 0 || tokens.reasoning > 0)
            .then_some(tokens)
    }

    const fn add(&mut self, other: Self) {
        self.input = self.input.saturating_add(other.input);
        self.output = self.output.saturating_add(other.output);
        self.reasoning = self.reasoning.saturating_add(other.reasoning);
        self.cache_read = self.cache_read.saturating_add(other.cache_read);
        self.cache_create =
            self.cache_create.saturating_add(other.cache_create);
    }
}

struct Usage {
    index: i64,
    time: Option<i64>,
    model: Option<String>,
    tokens: Tokens,
}

fn unsupported(error: &rusqlite::Error) -> crate::Error {
    format!("unsupported Antigravity CLI database: {error}").into()
}

fn models(connection: &Connection) -> crate::Result<HashMap<u64, String>> {
    let mut statement = connection
        .prepare("SELECT data FROM gen_metadata WHERE data IS NOT NULL")
        .map_err(|error| unsupported(&error))?;
    let mut rows = statement.query([])?;
    let mut models = HashMap::new();
    while let Some(row) = rows.next()? {
        let chat = proto::Generation::decode(&row.get::<_, Vec<u8>>(0)?)
            .map_err(|error| {
                format!("invalid Antigravity CLI generation metadata: {error}")
            })?
            .chat
            .unwrap_or_default();
        if let (Some(id), Some(model)) =
            (chat.model_id, chat.model.filter(|model| !model.is_empty()))
        {
            models.insert(id, model);
        }
    }
    Ok(models)
}

fn native_time(time: Option<proto::Time>) -> Option<i64> {
    let time = time.filter(|time| time.seconds > 0)?;
    time.seconds
        .checked_mul(1000)?
        .checked_add(time.nanos / 1_000_000)
}

fn tool(
    call: proto::ToolCall,
    kind: i64,
    status: i64,
    time: i64,
) -> Option<Part> {
    let name = call
        .name
        .filter(|name| !name.is_empty())
        .or(call.secondary_name)?;
    let input = call.input.map(|input| {
        serde_json::from_str(&input).unwrap_or(Value::String(input))
    });
    Some(Part::tool(
        &name,
        call.id.as_deref().unwrap_or_default(),
        json!({
            "status": "unknown",
            "input": input,
            "output": null,
            "metadata": {
                "antigravity_step_type": kind,
                "antigravity_status": status,
            },
        }),
        time,
    ))
}

impl Transcript {
    fn push(
        &mut self,
        mut message: Message,
        inferred: bool,
        pending: &mut Vec<Usage>,
    ) {
        message.inferred_time = inferred;
        if message.role == "assistant" {
            message.agent = Some("antigravity-cli".into());
            self.attach(&mut message, pending);
        }
        self.messages.push(message);
    }

    fn attach(&mut self, message: &mut Message, pending: &mut Vec<Usage>) {
        if pending.is_empty() {
            return;
        }
        let mut tokens = Tokens::default();
        for usage in pending.drain(..) {
            tokens.add(usage.tokens);
            if let Some(model) = usage.model {
                message.model = Some(model.clone().into());
                self.model = Some(model);
            }
        }
        self.input = self.input.saturating_add(tokens.input);
        // Session output includes reasoning so totals reconcile as input + output.
        let output = tokens.output.saturating_add(tokens.reasoning);
        self.output = self.output.saturating_add(output);
        self.total = Some(
            self.total
                .unwrap_or_default()
                .saturating_add(tokens.input.saturating_add(output)),
        );
        message.tokens.clone_from(
            json!({
                "input": tokens.input,
                "output": tokens.output,
                "reasoning": tokens.reasoning,
                "cache": {"read": tokens.cache_read, "write": tokens.cache_create},
            })
            .as_object()
            .unwrap(),
        );
    }
}

pub fn read(
    connection: &Connection,
    id: &str,
    fallback: i64,
) -> crate::Result<Transcript> {
    let models = models(connection)?;
    let mut statement = connection
        .prepare(
            "SELECT idx, step_type, status, step_payload FROM steps ORDER BY idx",
        )
        .map_err(|error| unsupported(&error))?;
    let mut rows = statement.query([])?;
    let mut transcript = Transcript::default();
    let mut seen = HashSet::new();
    let mut pending = Vec::new();
    while let Some(row) = rows.next()? {
        let index: i64 = row.get(0)?;
        let kind: i64 = row.get(1)?;
        let status: i64 = row.get(2)?;
        let Some(payload) = row.get::<_, Option<Vec<u8>>>(3)? else {
            transcript.unsupported += 1;
            continue;
        };
        let step = proto::Step::decode(&payload).map_err(|error| {
            format!("invalid Antigravity CLI step {index}: {error}")
        })?;
        let metadata = step.metadata.unwrap_or_default();
        let created = native_time(metadata.created);
        let time = created.unwrap_or(fallback);
        for usage in metadata
            .usage
            .into_iter()
            .chain(metadata.retries.into_iter().filter_map(|retry| retry.usage))
        {
            let Some(tokens) = Tokens::new(&usage) else {
                continue;
            };
            let ids = [
                ("response", usage.response_id),
                ("provider", usage.provider_message_id),
                ("message", usage.message_id),
            ]
            .into_iter()
            .filter_map(|(kind, id)| {
                Some(format!("{kind}:{}", id.filter(|id| !id.is_empty())?))
            });
            // Every id is recorded so a later copy sharing any of them is skipped.
            if !ids.fold(true, |fresh, id| seen.insert(id) && fresh) {
                continue;
            }
            pending.push(Usage {
                index,
                time: created,
                model: usage.model_id.and_then(|id| models.get(&id)).cloned(),
                tokens,
            });
        }
        let part = match kind {
            14 => step
                .user
                .and_then(|user| {
                    user.text
                        .or_else(|| user.content.and_then(|text| text.text))
                })
                .filter(|text| !text.is_empty())
                .map(|text| ("user", Part::text(text, time))),
            15 => step
                .assistant
                .and_then(|text| text.text)
                .filter(|text| !text.is_empty())
                .map(|text| ("assistant", Part::text(text, time))),
            23 => {
                if let Some(title) = step
                    .title
                    .and_then(|title| title.text)
                    .filter(|title| !title.is_empty())
                {
                    transcript.title = Some(title);
                }
                continue;
            }
            _ => None,
        };
        let part = part.or_else(|| {
            Some(("assistant", tool(metadata.call?, kind, status, time)?))
        });
        let Some((role, part)) = part else {
            transcript.unsupported += 1;
            continue;
        };
        transcript.push(
            Message::new(format!("{id}:{index}"), role, time, vec![part]),
            created.is_none(),
            &mut pending,
        );
    }
    if let Some(first) = pending.first() {
        let message = Message::new(
            format!("{id}:{}:usage", first.index),
            "assistant",
            first.time.unwrap_or(fallback),
            Vec::new(),
        );
        let inferred = first.time.is_none();
        transcript.push(message, inferred, &mut pending);
    }
    Ok(transcript)
}
