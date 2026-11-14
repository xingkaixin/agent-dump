use super::WorkspaceHits;
use super::proto::{self, Message as _};
use crate::providers::sqlite::connection::has_column;
use crate::session::{Message, Part};
use rusqlite::Connection;
use serde_json::{Map, Value, json};
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
    pub hits: WorkspaceHits,
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

struct ToolEvidence {
    kind: i64,
    status: i64,
    time: i64,
    input: Option<Value>,
    output: Option<String>,
    error: Option<String>,
}

fn tool(name: &str, call_id: &str, evidence: ToolEvidence) -> Part {
    let mut state = Map::from_iter([
        (
            "status".into(),
            Value::String(
                if evidence.error.is_some() {
                    "error"
                } else {
                    "unknown"
                }
                .into(),
            ),
        ),
        ("input".into(), evidence.input.unwrap_or(Value::Null)),
        (
            "output".into(),
            evidence.output.map_or(Value::Null, Value::String),
        ),
        (
            "metadata".into(),
            json!({
                "antigravity_step_type": evidence.kind,
                "antigravity_status": evidence.status,
            }),
        ),
    ]);
    if let Some(error) = evidence.error {
        state.insert("error".into(), Value::String(error));
    }
    Part::tool(name, call_id, Value::Object(state), evidence.time)
}

fn tool_output(step: &proto::Step, kind: i64) -> Option<String> {
    match kind {
        132 => step.tool.as_ref()?.result.as_ref()?.text.clone(),
        8 => step.view_file.as_ref()?.content.clone(),
        21 => step.run_command.as_ref()?.output.as_ref()?.text.clone(),
        38 => step.mcp.as_ref()?.result.clone(),
        _ => None,
    }
    .filter(|text| !text.is_empty())
}

fn tool_error(error: proto::ErrorDetails) -> Option<String> {
    let mut parts = Vec::new();
    for text in [error.message, error.details].into_iter().flatten() {
        if !text.trim().is_empty() && !parts.contains(&text) {
            parts.push(text);
        }
    }
    (!parts.is_empty()).then(|| parts.join("\n"))
}

fn swarm_child_id(
    tool: &str,
    input: Option<&Value>,
    output: Option<&str>,
) -> Option<String> {
    if tool != "swarm" || input?.get("action")?.as_str()? != "add" {
        return None;
    }
    let output = output?;
    let body = if output.starts_with("Created At: ") {
        let (_, rest) = output.split_once('\n')?;
        rest.strip_prefix("Completed At: ")?.split_once('\n')?.1
    } else {
        output
    };
    let result: Value = serde_json::from_str(body).ok()?;
    if result.get("status")?.as_str()? != "added" {
        return None;
    }
    result
        .get("conversation_id")?
        .as_str()
        .filter(|id| !id.trim().is_empty())
        .map(str::to_owned)
}

fn user_prompt_text(user: proto::UserPrompt) -> Option<String> {
    user.text.filter(|text| !text.is_empty()).or_else(|| {
        let joined: String = user
            .items
            .into_iter()
            .filter_map(|item| item.text)
            .collect();
        (!joined.is_empty()).then_some(joined)
    })
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
    candidates: &[String],
) -> crate::Result<Transcript> {
    let models = models(connection)?;
    let sql = if has_column(connection, "steps", "error_details")? {
        "SELECT idx, step_type, status, step_payload, error_details \
         FROM steps ORDER BY idx"
    } else {
        "SELECT idx, step_type, status, step_payload, NULL \
         FROM steps ORDER BY idx"
    };
    let mut statement = connection
        .prepare(sql)
        .map_err(|error| unsupported(&error))?;
    let mut rows = statement.query([])?;
    let mut transcript = Transcript {
        hits: WorkspaceHits::new(candidates.len()),
        ..Transcript::default()
    };
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
        let output = tool_output(&step, kind);
        let error = row
            .get::<_, Option<Vec<u8>>>(4)?
            .map(|data| proto::ErrorDetails::decode(&data))
            .transpose()
            .map_err(|error| {
                format!(
                    "invalid Antigravity CLI error at step {index}: {error}"
                )
            })?
            .and_then(tool_error)
            .or_else(|| step.error.and_then(tool_error));
        let metadata = step.metadata.unwrap_or_default();
        let created = native_time(metadata.created);
        let time = created.unwrap_or(fallback);
        let step_model = metadata.model.and_then(|model| {
            model
                .api_name
                .filter(|name| !name.is_empty())
                .or_else(|| model.name.filter(|name| !name.is_empty()))
        });
        // Retries can switch models; the step model describes only the primary request.
        for (usage, fallback_model) in metadata
            .usage
            .into_iter()
            .map(|usage| (usage, step_model.clone()))
            .chain(
                metadata
                    .retries
                    .into_iter()
                    .filter_map(|retry| retry.usage)
                    .map(|usage| (usage, None)),
            )
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
                model: match usage.model_id {
                    Some(id) => models.get(&id).cloned(),
                    None => fallback_model,
                },
                tokens,
            });
        }
        let part = match kind {
            14 => step.user.and_then(|user| {
                if !candidates.is_empty() {
                    super::record_user_context(
                        &user,
                        candidates,
                        &mut transcript.hits.direct,
                    );
                }
                user_prompt_text(user)
                    .map(|text| ("user", Part::text(text, time), None))
            }),
            15 => step
                .assistant
                .and_then(|text| text.text)
                .filter(|text| !text.is_empty())
                .map(|text| ("assistant", Part::text(text, time), None)),
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
            let call = metadata.call?;
            let name = call
                .name
                .filter(|name| !name.is_empty())
                .or(call.secondary_name)?;
            let input = call.input.map(|input| {
                serde_json::from_str(&input).unwrap_or(Value::String(input))
            });
            if !candidates.is_empty()
                && let Some(input) = &input
            {
                super::record_tool_input(
                    input,
                    candidates,
                    &mut transcript.hits,
                );
            }
            let subagent_id = error
                .is_none()
                .then(|| {
                    swarm_child_id(&name, input.as_ref(), output.as_deref())
                })
                .flatten();
            let part = tool(
                &name,
                call.id.as_deref().unwrap_or_default(),
                ToolEvidence {
                    kind,
                    status,
                    time,
                    input,
                    output,
                    error,
                },
            );
            Some(("assistant", part, subagent_id))
        });
        let Some((role, part, subagent_id)) = part else {
            transcript.unsupported += 1;
            continue;
        };
        let mut message =
            Message::new(format!("{id}:{index}"), role, time, vec![part]);
        message.subagent_id = subagent_id;
        transcript.push(message, created.is_none(), &mut pending);
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

pub fn workspace_hits(
    connection: &Connection,
    candidates: &[String],
) -> crate::Result<WorkspaceHits> {
    let mut statement = connection
        .prepare("SELECT idx, step_type, step_payload FROM steps ORDER BY idx")
        .map_err(|error| unsupported(&error))?;
    let mut rows = statement.query([])?;
    let mut hits = WorkspaceHits::new(candidates.len());
    while let Some(row) = rows.next()? {
        let index: i64 = row.get(0)?;
        let kind: i64 = row.get(1)?;
        let Some(payload) = row.get::<_, Option<Vec<u8>>>(2)? else {
            continue;
        };
        let step = proto::Step::decode(&payload).map_err(|error| {
            format!("invalid Antigravity CLI step {index}: {error}")
        })?;
        if kind == 23 {
            continue;
        }
        let has_text = match kind {
            14 => {
                if let Some(user) = step.user {
                    super::record_user_context(
                        &user,
                        candidates,
                        &mut hits.direct,
                    );
                    user_prompt_text(user).is_some()
                } else {
                    false
                }
            }
            15 => step
                .assistant
                .and_then(|text| text.text)
                .is_some_and(|text| !text.is_empty()),
            _ => false,
        };
        if !has_text
            && let Some(call) = step.metadata.and_then(|metadata| metadata.call)
            && call
                .name
                .filter(|name| !name.is_empty())
                .or(call.secondary_name)
                .is_some()
            && let Some(raw_input) = call.input
        {
            let input = serde_json::from_str(&raw_input)
                .unwrap_or(Value::String(raw_input));
            super::record_tool_input(&input, candidates, &mut hits);
        }
    }
    Ok(hits)
}
