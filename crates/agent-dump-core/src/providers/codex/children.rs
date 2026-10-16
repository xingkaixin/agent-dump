use crate::compat::value::text;
use crate::providers::codex::rollout;
use crate::providers::codex::usage::{Totals, Usage};
use crate::providers::contract::{DiagnosticSink, RecoverableDiagnostic};
use crate::session::{Message, Part, parse_timestamp};
use serde_json::Value;
use std::collections::HashMap;
use std::io::Read;
use std::path::{Path, PathBuf};

const PREFIX: u64 = 8 * 1024;

/// Subagent rollouts keyed by their parent thread.
pub fn index(paths: &[PathBuf]) -> HashMap<String, Vec<PathBuf>> {
    let mut children = HashMap::<String, Vec<PathBuf>>::new();
    for path in paths {
        if let Ok(Some(parent)) = parent(path) {
            children.entry(parent).or_default().push(path.clone());
        }
    }
    children
}

fn parent(path: &Path) -> crate::Result<Option<String>> {
    let mut prefix = Vec::new();
    rollout::open(path)?.take(PREFIX).read_to_end(&mut prefix)?;
    if !prefix.windows(8).any(|window| window == b"subagent") {
        return Ok(None);
    }
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
    let stem = rollout::stem(path);
    let parts: Vec<_> = stem.split('-').collect();
    let mut id = parts[parts.len().saturating_sub(5)..].join("-");
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
