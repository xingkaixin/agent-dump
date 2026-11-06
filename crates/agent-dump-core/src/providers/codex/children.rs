use crate::compat::value::text;
use crate::providers::codex::rollout;
use crate::providers::codex::usage::{Totals, Usage};
use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use crate::session::{Message, Part, parse_timestamp};
use regex::Regex;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

static THREAD_ID: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        .unwrap()
});

/// Absorbs clock steps between a spawn record and the child's id.
const SPAWN_MARGIN: i64 = 1000;

/// Threads a parent rollout points at.
#[derive(Default)]
pub struct References {
    ids: HashSet<String>,
    /// Multi-agent v2 `spawn_agent` returns a task name and
    /// `spawn_agents_on_csv` a job id, so their children are matched by
    /// the creation time inside the thread id.
    spawns: Vec<(i64, i64)>,
    pending: HashMap<String, i64>,
    last: i64,
}

impl References {
    pub fn visit(&mut self, record: &Value) {
        mentions(record, &mut self.ids);
        let Some(time) = time(record) else {
            return;
        };
        self.last = self.last.max(time);
        let payload = &record["payload"];
        if record["type"] != "response_item" {
            return;
        }
        let call = text(&payload["call_id"]);
        match text(&payload["type"]) {
            "function_call"
                if matches!(
                    text(&payload["name"]),
                    "spawn_agent" | "spawn_agents_on_csv"
                ) =>
            {
                self.pending.insert(call.to_owned(), time);
            }
            "function_call_output" => {
                if let Some(start) = self.pending.remove(call) {
                    self.spawns.push((start, time));
                }
            }
            _ => {}
        }
    }
}

fn mentions(value: &Value, ids: &mut HashSet<String>) {
    match value {
        Value::String(text) => ids.extend(
            THREAD_ID
                .find_iter(text)
                .map(|found| found.as_str().to_owned()),
        ),
        Value::Array(items) => {
            for item in items {
                mentions(item, ids);
            }
        }
        Value::Object(fields) => {
            for item in fields.values() {
                mentions(item, ids);
            }
        }
        _ => {}
    }
}

/// Subagent rollouts of `parent` among the threads its rollout references.
pub fn resolve(
    parent: &str,
    references: References,
    paths: &[PathBuf],
) -> Vec<PathBuf> {
    let References {
        ids,
        mut spawns,
        pending,
        last,
    } = references;
    spawns.extend(pending.into_values().map(|start| (start, last)));
    paths
        .iter()
        .filter(|path| {
            let id = rollout::id(path);
            id != parent
                && (ids.contains(&id)
                    || created(&id).is_some_and(|time| {
                        spawns.iter().any(|&(start, end)| {
                            (start - SPAWN_MARGIN..=end + SPAWN_MARGIN)
                                .contains(&time)
                        })
                    }))
        })
        .filter(|path| {
            matches!(parent_thread(path), Ok(Some(found)) if found == parent)
        })
        .cloned()
        .collect()
}

/// Codex thread ids are UUID v7, which lead with their creation time.
fn created(id: &str) -> Option<i64> {
    if id.as_bytes().get(14) != Some(&b'7') {
        return None;
    }
    i64::from_str_radix(&id.get(..13)?.replace('-', ""), 16).ok()
}

fn parent_thread(path: &Path) -> crate::Result<Option<String>> {
    let mut header = None;
    rollout::lines(path, |_, line, _| {
        header = rollout::object(line);
        Ok(false)
    })?;
    let header = header.unwrap_or_default();
    let payload = &header["payload"];
    let parent = text(&payload["parent_thread_id"]);
    Ok(
        (payload["thread_source"] == "subagent" && !parent.is_empty())
            .then(|| parent.to_owned()),
    )
}

struct Child {
    totals: Totals,
    message: Option<Message>,
}

fn time(record: &Value) -> Option<i64> {
    [&record["timestamp"], &record["payload"]["timestamp"]]
        .into_iter()
        .find_map(|value| parse_timestamp(text(value).trim()))
        .map(crate::session::timestamp::Timestamp::as_millisecond)
}

fn summary(path: &Path) -> crate::Result<Child> {
    let mut id = rollout::id(path);
    let mut nickname = None;
    let mut usage = Usage::default();
    let mut meta_seen = false;
    let mut latest = None;
    let mut final_answer = None;
    let fallback = crate::session::timestamp::Timestamp::try_from(
        path.metadata()?.modified()?,
    )?
    .as_millisecond();
    rollout::scan(path, &mut |_| Ok(()), |record, _| {
        let payload = &record["payload"];
        match text(&record["type"]) {
            // A forked rollout replays its parent's session_meta later.
            "session_meta" if !meta_seen => {
                meta_seen = true;
                if let Some(meta_id) =
                    payload["id"].as_str().filter(|id| !id.is_empty())
                {
                    meta_id.clone_into(&mut id);
                }
                nickname =
                    payload["agent_nickname"].as_str().map(str::to_owned);
                usage = Usage::new(payload);
            }
            "turn_context" => usage.turn(payload),
            "event_msg" if payload["type"] == "token_count" => {
                usage.consume(payload);
            }
            "token_usage_record" => usage.record(payload),
            "compacted" => usage.compacted(payload),
            "response_item"
                if payload["type"] == "message"
                    && payload["role"] == "assistant" =>
            {
                let body = payload["content"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter(|item| item["type"] == "output_text")
                    .filter_map(|item| item["text"].as_str())
                    .collect::<Vec<_>>()
                    .join("\n");
                let body = crate::providers::text::clean(&body);
                if body.is_empty() {
                    return Ok(());
                }
                let time = time(&record).unwrap_or(fallback);
                let mut message = Message::new(
                    text(&payload["id"]).to_owned(),
                    "assistant",
                    time,
                    vec![Part::text(body, time)],
                );
                message.agent = Some("codex".into());
                if record["phase"] == "final_answer"
                    || payload["phase"] == "final_answer"
                {
                    final_answer = Some(message.clone());
                }
                latest = Some(message);
            }
            _ => {}
        }
        Ok(())
    })?;
    let message = final_answer.or(latest).map(|mut message| {
        if message.id.is_empty() {
            message.id = format!("codex-subagent-{id}");
        }
        message.subagent_id = Some(id);
        message.nickname = nickname;
        message
    });
    Ok(Child {
        totals: usage.totals(),
        message,
    })
}

fn reported(messages: &[Message], message: &Message) -> bool {
    let reply = message.parts.iter().find_map(|part| match part {
        Part::Text(part) => Some(&part.text),
        _ => None,
    });
    messages.iter().any(|visible| {
        (message.subagent_id.is_some()
            && message.subagent_id == visible.subagent_id)
            || (message.nickname.is_some()
                && message.nickname == visible.nickname
                && visible.parts.iter().any(|part| {
                    matches!(part, Part::Text(part) if Some(&part.text) == reply)
                }))
    })
}

/// Adds subagent usage and, when the parent never received a completion
/// notification, the subagent's final reply.
pub fn merge(
    paths: &[PathBuf],
    messages: &mut Vec<Message>,
    totals: &mut Totals,
    diagnostics: &mut DiagnosticSink<'_>,
) -> crate::Result<()> {
    let mut children = Vec::new();
    for path in paths {
        match summary(path) {
            Ok(child) => children.push(child),
            Err(error) => diagnostics(
                RecoverableDiagnostic::MessageConvertFailed(error.to_string()),
            )?,
        }
    }
    children.sort_by_key(|child| {
        child
            .message
            .as_ref()
            .map_or(0, |message| message.time_created)
    });
    for child in children {
        *totals += child.totals;
        let Some(message) = child.message else {
            continue;
        };
        if reported(messages, &message) {
            continue;
        }
        let index = messages
            .iter()
            .rposition(|visible| visible.time_created <= message.time_created)
            .map_or(0, |index| index + 1);
        messages.insert(index, message);
    }
    Ok(())
}
