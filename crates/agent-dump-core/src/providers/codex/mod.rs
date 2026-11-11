mod children;
pub(super) mod enrichment;
mod exec;
pub(super) mod patch;
mod rollout;
pub(super) mod transcript;
mod usage;

use crate::compat::value::text;
use crate::providers::contract::{
    DiagnosticSink, Provider, RecoverableDiagnostic, SessionFailure, Window,
};
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::providers::jsonl;
use crate::providers::title::normalize_title;
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, parse_timestamp};
use serde_json::Value;
use std::collections::HashMap;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

const TITLE_RECORDS: usize = 20;
const TAIL_WINDOW: u64 = 64 * 1024;
const TAIL_LIMIT: u64 = 8 * 1024 * 1024;

static RECORD: jsonl::Shape = jsonl::Shape::Fields(&[
    ("type", jsonl::Shape::Leaf),
    ("timestamp", jsonl::Shape::Leaf),
    (
        "payload",
        jsonl::Shape::Fields(&[
            ("type", jsonl::Shape::Leaf),
            ("role", jsonl::Shape::Leaf),
            ("model", jsonl::Shape::Leaf),
            ("timestamp", jsonl::Shape::Leaf),
        ]),
    ),
]);

pub struct Codex {
    roots: SourceRoots,
    titles: Option<HashMap<String, String>>,
    paths: Vec<PathBuf>,
}

struct Scan {
    header: Option<Value>,
    head: Vec<Value>,
    activity: Activity,
    complete: bool,
}

#[derive(Default)]
struct Activity {
    updated: Option<Timestamp>,
    model: Option<String>,
    count: usize,
}

impl Activity {
    fn visit(&mut self, record: &Value) -> crate::Result<()> {
        let payload = &record["payload"];
        if payload["type"].is_array() || payload["type"].is_object() {
            return Err(format!(
                "unhashable type: '{}'",
                crate::compat::value::type_name(&payload["type"])
            )
            .into());
        }
        if active(record)
            && let Some(time) = record_time(record)
        {
            self.updated = self.updated.max(Some(time));
        }
        if let Some(model) = meta_model(record) {
            self.model = Some(model);
        }
        if record["type"] == "response_item"
            && matches!(
                text(&payload["type"]),
                "message" | "function_call" | "function_call_output"
            )
        {
            self.count += 1;
        }
        Ok(())
    }
}

fn active(record: &Value) -> bool {
    let payload = &record["payload"];
    match text(&record["type"]) {
        "response_item" => match text(&payload["type"]) {
            "message" => matches!(text(&payload["role"]), "user" | "assistant"),
            "reasoning"
            | "function_call"
            | "function_call_output"
            | "custom_tool_call"
            | "custom_tool_call_output" => true,
            _ => false,
        },
        "event_msg" => matches!(
            text(&payload["type"]),
            "task_started"
                | "task_complete"
                | "turn_aborted"
                | "token_count"
                | "item_completed"
                | "user_message"
                | "agent_message"
                | "agent_reasoning"
        ),
        "token_usage_record" => true,
        _ => false,
    }
}

fn record_time(record: &Value) -> Option<Timestamp> {
    let time = |value: &Value| parse_timestamp(text(value).trim());
    time(&record["timestamp"]).max(time(&record["payload"]["timestamp"]))
}

pub(super) fn meta_model(record: &Value) -> Option<String> {
    if !matches!(text(&record["type"]), "session_meta" | "turn_context") {
        return None;
    }
    let model = text(&record["payload"]["model"]).trim();
    (!model.is_empty()).then(|| model.to_owned())
}

/// Index titles and message titles keep only their first visible line.
fn title_line(value: &str) -> Option<String> {
    crate::providers::text::clean(value)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(normalize_title)
}

fn message_title(head: &[Value]) -> Option<String> {
    head.iter().find_map(|record| {
        let payload = &record["payload"];
        if record["type"] != "response_item"
            || payload["type"] != "message"
            || payload["role"] != "user"
        {
            return None;
        }
        let body = enrichment::user_text(&payload["content"]);
        if enrichment::context(&payload["content"], &body)
            || body.trim_start().starts_with("<subagent_notification>")
        {
            return None;
        }
        title_line(&body)
    })
}

/// Reopening a rollout appends settings records; the last activity
/// before them is usually within the final window.
fn recent(
    path: &Path,
    size: u64,
) -> crate::Result<(Activity, Option<Timestamp>)> {
    let mut file = crate::storage::source_io::open(path)?;
    let floor = size.saturating_sub(TAIL_LIMIT);
    let mut recent = Activity::default();
    let mut last = None;
    let mut end = size;
    let mut carry = Vec::new();
    while end > floor && recent.updated.is_none() {
        let start = end.saturating_sub(TAIL_WINDOW).max(floor);
        let mut chunk = vec![0; usize::try_from(end - start)?];
        crate::storage::source_io::at(path, file.seek(SeekFrom::Start(start)))?;
        crate::storage::source_io::at(path, file.read_exact(&mut chunk))?;
        chunk.append(&mut carry);
        let first = if start == 0 {
            0
        } else {
            chunk
                .iter()
                .position(|byte| *byte == b'\n')
                .map_or(chunk.len(), |index| index + 1)
        };
        for line in chunk[first..].rsplit(|byte| *byte == b'\n') {
            let Some(record) = rollout::object(line) else {
                continue;
            };
            last = last.or_else(|| record_time(&record));
            if recent.model.is_none() {
                recent.model = meta_model(&record);
            }
            if active(&record)
                && let Some(time) = record_time(&record)
            {
                recent.updated = Some(time);
                break;
            }
        }
        chunk.truncate(first);
        carry = chunk;
        end = start;
    }
    Ok((recent, last))
}

impl Codex {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self::new(SourceRoots::new(
            || file_sessions::environment_root("CODEX_HOME", ".codex"),
            "sessions",
            "data/codex",
            "CODEX_HOME/sessions",
        )))
    }

    const fn new(roots: SourceRoots) -> Self {
        Self {
            roots,
            titles: None,
            paths: Vec::new(),
        }
    }

    fn title(
        &mut self,
        id: &str,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Option<String>> {
        if self.titles.is_none() {
            let mut titles = HashMap::new();
            let index =
                self.roots.configured_root()?.join("session_index.jsonl");
            if index.exists()
                && let Err(error) =
                    jsonl::scan(&index, &mut |_| Ok(()), |record, _| {
                        let id = text(&record["id"]);
                        if !id.trim().is_empty()
                            && let Some(title) =
                                title_line(text(&record["thread_name"]))
                        {
                            titles.insert(id.to_owned(), title);
                        }
                        Ok(())
                    })
            {
                diagnostics(RecoverableDiagnostic::TitleCacheFailed(
                    error.to_string(),
                ))?;
            }
            self.titles = Some(titles);
        }
        Ok(self
            .titles
            .as_ref()
            .and_then(|titles| titles.get(id))
            .cloned())
    }

    /// Archived rollouts belong to the configured Codex home only.
    fn archive(&self) -> Option<PathBuf> {
        let owned = self.roots.owned();
        (self.roots.base.as_deref() == Some(&owned.join("sessions")))
            .then(|| owned.join("archived_sessions"))
    }

    fn scope(&self) -> Option<PathBuf> {
        if self.archive().is_some() {
            Some(self.roots.owned().to_owned())
        } else {
            self.roots.base.clone()
        }
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        let mut files = self
            .roots
            .files(None, |path, _| rollout::is_rollout(path))?;
        if let Some(archive) = self.archive().filter(|path| path.exists()) {
            for entry in walkdir::WalkDir::new(&archive) {
                match entry {
                    Ok(entry) => {
                        if !entry.file_type().is_dir()
                            && rollout::is_rollout(entry.path())
                        {
                            files.paths.push(entry.into_path());
                        }
                    }
                    Err(error) => files.failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(
                            error.path().unwrap_or(&archive),
                        ),
                        error: error.into(),
                    }),
                }
            }
        }
        rollout::prefer_plain(&mut files.paths);
        self.paths.clone_from(&files.paths);
        Ok(files)
    }

    fn scan(path: &Path) -> crate::Result<Scan> {
        if rollout::compressed(path) {
            let mut scan = Scan {
                header: None,
                head: Vec::new(),
                activity: Activity::default(),
                complete: true,
            };
            let mut first = true;
            rollout::lines(path, |_, line, _| {
                let record = if scan.head.len() < TITLE_RECORDS {
                    rollout::object(line)
                } else {
                    jsonl::pruned(line, &RECORD)
                };
                if std::mem::take(&mut first) {
                    scan.header.clone_from(&record);
                }
                if let Some(record) = record {
                    scan.activity.visit(&record)?;
                    if scan.head.len() < TITLE_RECORDS {
                        scan.head.push(record);
                    }
                }
                Ok(true)
            })?;
            return Ok(scan);
        }
        let metadata = jsonl::metadata(path, TITLE_RECORDS, Some(&RECORD))?;
        let mut activity = Activity::default();
        for record in &metadata.records {
            activity.visit(record)?;
        }
        if !metadata.complete {
            let (recent, last) = recent(path, path.metadata()?.len())?;
            activity.updated = activity.updated.max(recent.updated.or(last));
            activity.model = recent.model.or(activity.model);
        }
        let mut head = metadata.records;
        head.truncate(TITLE_RECORDS);
        Ok(Scan {
            header: metadata.header,
            head,
            activity,
            complete: metadata.complete,
        })
    }

    fn parse(
        &mut self,
        path: &Path,
        scan: Scan,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Option<Session>> {
        let Some(header) = scan.header else {
            return Ok(None);
        };
        let payload = &header["payload"];
        if !payload.is_null() && !payload.is_object() {
            return Err(format!(
                "'{}' object has no attribute 'get'",
                crate::compat::value::type_name(payload)
            )
            .into());
        }
        let mut id = text(&payload["id"]).to_owned();
        if id.is_empty() {
            id = rollout::id(path);
        }
        let created_at = parse_timestamp(text(&payload["timestamp"]))
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        let title = self
            .title(&id, diagnostics)?
            .or_else(|| message_title(&scan.head))
            .or_else(|| {
                crate::providers::title::value_basename(&payload["cwd"])
            })
            .unwrap_or_else(|| "Untitled Session".into());
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at: scan.activity.updated.unwrap_or(created_at),
            subtargets: Vec::new(),
            source_metadata: serde_json::json!({
                "cwd": payload.get("cwd").cloned().unwrap_or_else(|| "".into())
            }),
            source_path: path.to_owned(),
            directory: text(&payload["cwd"]).to_owned(),
            version: payload
                .get("cli_version")
                .cloned()
                .unwrap_or_else(|| "".into()),
            model: scan.activity.model.unwrap_or_default(),
            project: None,
            message_count: scan.complete.then_some(scan.activity.count),
        }))
    }
}

impl Provider for Codex {
    fn discover(
        &mut self,
        window: Window,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.titles = None;
        file_sessions::discover(
            self.files()?,
            window,
            true,
            Self::scan,
            |path, scan, _| self.parse(path, scan, diagnostics),
        )
    }

    fn find(
        &mut self,
        id: &str,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        self.titles = None;
        let suffix = format!("-{id}");
        let files = self.files()?;
        file_sessions::find(
            self.scope().as_deref(),
            files,
            id,
            |path| rollout::stem(path).ends_with(&suffix),
            |path| self.parse(path, Self::scan(path)?, diagnostics),
        )
    }

    fn read(
        &self,
        session: &Session,
        zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            return Err(crate::providers::error::ProviderError::missing(
                ["session source file is missing"; 2],
                &session.source_path,
                Vec::new(),
                crate::providers::contract::source_roots(self)?,
                vec![
                    [
                        "Confirm the Codex session file is still under \
                         `CODEX_HOME/sessions` or the local development \
                         data directory.",
                        "确认 Codex 会话文件仍在 `CODEX_HOME/sessions` \
                         或本地开发数据目录。",
                    ],
                    [
                        "Re-run `agent-dump --list` to confirm the session \
                         id still exists.",
                        "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。",
                    ],
                ],
            )
            .into());
        }
        transcript::read(session, zh, &self.paths, diagnostics)
    }

    fn json_payload(&self, data: &SessionData) -> serde_json::Value {
        serde_json::to_value(enrichment::json_payload(data)).unwrap()
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write(path: &Path, records: &[Value]) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let mut text = records
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n");
        text.push('\n');
        std::fs::write(path, text).unwrap();
    }

    fn fixed(root: &Path) -> Codex {
        Codex::new(SourceRoots::fixed(
            root.into(),
            "sessions",
            root.join("fallback"),
            "CODEX_HOME/sessions",
        ))
    }

    fn meta(id: &str, extra: Value) -> Value {
        let mut payload = serde_json::json!({
            "id": id, "timestamp": "2026-01-15T00:00:00Z", "cwd": "/work/project"
        });
        if let Value::Object(extra) = extra {
            payload.as_object_mut().unwrap().extend(extra);
        }
        let mut record = serde_json::json!({"type": "session_meta"});
        record["payload"] = payload;
        record
    }

    fn item(time: &str, payload: Value) -> Value {
        event("response_item", time, payload)
    }

    fn event(kind: &str, time: &str, payload: Value) -> Value {
        let mut record = serde_json::json!({"type": kind, "timestamp": time});
        record["payload"] = payload;
        record
    }

    fn said(time: &str, role: &str, text: &str) -> Value {
        let kind = if role == "assistant" {
            "output_text"
        } else {
            "input_text"
        };
        item(
            time,
            serde_json::json!({
                "type": "message",
                "role": role,
                "content": [{"type": kind, "text": text}]
            }),
        )
    }

    fn read(provider: &mut Codex, id: &str) -> SessionData {
        let session =
            provider.find(id, &mut |_| Ok(())).unwrap().session.unwrap();
        provider.read(&session, false, &mut |_| Ok(())).unwrap()
    }

    #[test]
    fn referenced_subagents_add_usage_and_missing_replies_to_the_parent() {
        let directory = tempfile::tempdir().unwrap();
        let sessions = directory.path().join("sessions");
        let parent = "019e0000-0000-7000-8000-000000000001";
        let forked = "019f0000-0000-7000-8000-000000000002";
        let reported = "019f0000-0000-7000-8000-000000000003";
        // UUIDv7 time of 2026-01-15T00:00:02.200Z, inside the spawn call.
        let spawned = "019bbef3-b898-7000-8000-000000000004";
        let usage = |last: u64, total: u64| {
            event(
                "event_msg",
                "2026-01-15T00:00:01Z",
                serde_json::json!({"type": "token_count", "info": {
                    "total_token_usage": {"input_tokens": total, "total_tokens": total},
                    "last_token_usage": {"input_tokens": last, "total_tokens": last}
                }}),
            )
        };
        let parent_turn = event(
            "turn_context",
            "2026-01-15T00:00:01Z",
            serde_json::json!({"turn_id": "019e0000-0001-7000-8000-000000000001"}),
        );
        write(
            &sessions
                .join(format!("rollout-2026-01-15T00-00-00-{parent}.jsonl")),
            &[
                meta(parent, Value::Null),
                said("2026-01-15T00:00:01Z", "user", "first"),
                parent_turn.clone(),
                usage(100, 100),
                event(
                    "event_msg",
                    "2026-01-15T00:00:01.500Z",
                    serde_json::json!({"type": "item_completed", "item": {
                        "type": "SubAgentActivity", "agent_thread_id": forked
                    }}),
                ),
                item(
                    "2026-01-15T00:00:02.100Z",
                    serde_json::json!({
                        "type": "function_call", "name": "spawn_agent",
                        "arguments": "{}", "call_id": "spawn"
                    }),
                ),
                item(
                    "2026-01-15T00:00:02.300Z",
                    serde_json::json!({
                        "type": "function_call_output", "call_id": "spawn",
                        "output": "{\"task_name\":\"/root/spawned\"}"
                    }),
                ),
                said("2026-01-15T00:00:03Z", "user", "last"),
                said(
                    "2026-01-15T00:00:04Z",
                    "user",
                    &format!(
                        "<subagent_notification>{}</subagent_notification>",
                        serde_json::json!({
                            "agent_id": reported,
                            "status": {"completed": "reported result"}
                        })
                    ),
                ),
            ],
        );
        let child = |id: &str, extra: Value, records: Vec<Value>| {
            let mut lines = vec![meta(
                id,
                serde_json::json!({"thread_source": "subagent", "parent_thread_id": parent}),
            )];
            lines[0]["payload"]
                .as_object_mut()
                .unwrap()
                .extend(extra.as_object().cloned().unwrap_or_default());
            lines.extend(records);
            write(
                &sessions
                    .join(format!("rollout-2026-01-15T00-00-00-{id}.jsonl")),
                &lines,
            );
        };
        let reply = |time: &str, text: &str, phase: &str| {
            let mut record = said(time, "assistant", text);
            record["payload"]["phase"] = phase.into();
            record
        };
        child(
            forked,
            serde_json::json!({"forked_from_id": parent, "agent_nickname": "Pascal"}),
            vec![
                meta(parent, Value::Null),
                parent_turn,
                usage(100, 100),
                event(
                    "turn_context",
                    "2026-01-15T00:00:02Z",
                    serde_json::json!({"turn_id": "019f0000-0001-7000-8000-000000000002"}),
                ),
                usage(7, 107),
                reply("2026-01-15T00:00:02Z", "child result", "final_answer"),
                reply("2026-01-15T00:00:02.500Z", "after final", "commentary"),
            ],
        );
        child(
            reported,
            Value::Null,
            vec![reply(
                "2026-01-15T00:00:04Z",
                "reported result",
                "final_answer",
            )],
        );
        child(
            spawned,
            Value::Null,
            vec![reply(
                "2026-01-15T00:00:02.800Z",
                "spawned result",
                "final_answer",
            )],
        );
        child(
            "019f0000-0000-7000-8000-000000000005",
            Value::Null,
            vec![reply(
                "2026-01-15T00:00:05Z",
                "unreferenced result",
                "final_answer",
            )],
        );
        let mut provider = fixed(directory.path());
        let data = read(&mut provider, parent);
        let texts: Vec<_> = data
            .messages
            .iter()
            .filter_map(|message| {
                Some((
                    message.parts[0].content()?,
                    message.subagent_id.as_deref(),
                    message.nickname.as_deref(),
                ))
            })
            .collect();
        assert_eq!(
            texts,
            [
                ("first", None, None),
                ("child result", Some(forked), Some("Pascal")),
                ("spawned result", Some(spawned), None),
                ("last", None, None),
                ("reported result", Some(reported), None),
            ]
        );
        assert_eq!(data.stats.total_input_tokens, 107.into());
        let child = read(&mut provider, forked);
        assert_eq!(child.stats.total_input_tokens, 7.into());
    }
}
