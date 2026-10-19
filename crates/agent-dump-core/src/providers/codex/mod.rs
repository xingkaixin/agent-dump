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
use std::sync::OnceLock;

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
    children: OnceLock<HashMap<String, Vec<PathBuf>>>,
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
            children: OnceLock::new(),
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
        self.children = OnceLock::new();
        Ok(files)
    }

    fn children(&self) -> &HashMap<String, Vec<PathBuf>> {
        self.children.get_or_init(|| children::index(&self.paths))
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
                let record = rollout::object(line);
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
            let stem = rollout::stem(path);
            let parts: Vec<_> = stem.split('-').collect();
            id = parts[parts.len().saturating_sub(5)..].join("-");
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
        let children = self.children().get(&session.id);
        transcript::read(
            session,
            zh,
            children.map_or(&[][..], Vec::as_slice),
            diagnostics,
        )
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        let mut sources = vec![session.source_path.clone()];
        if let Some(children) = self.children().get(&session.id) {
            sources.extend(children.iter().cloned());
        }
        sources
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
    use crate::session::Part;

    #[test]
    fn title_index_follows_configuration_while_session_root_stays_selected() {
        let directory = tempfile::tempdir().unwrap();
        let first = directory.path().join("first");
        let second = directory.path().join("second");
        for (root, title) in [(&first, "First"), (&second, "  Second\nnext")] {
            std::fs::create_dir_all(root.join("sessions")).unwrap();
            std::fs::write(
                root.join("session_index.jsonl"),
                serde_json::json!({"id":"kept", "thread_name":title})
                    .to_string(),
            )
            .unwrap();
        }
        let source = first.join("sessions/rollout-kept.jsonl");
        std::fs::write(
            &source,
            r#"{"type":"session_meta","payload":{"id":"kept","timestamp":"2026-01-15T00:00:00Z"}}"#,
        )
        .unwrap();
        let configured =
            std::sync::Arc::new(std::sync::Mutex::new(first.clone()));
        let mut provider = Codex::new(SourceRoots::new(
            {
                let configured = configured.clone();
                move || Ok(configured.lock().unwrap().clone())
            },
            "sessions",
            directory.path().join("fallback"),
            "Synthetic Codex",
        ));
        assert_eq!(
            provider
                .find("kept", &mut |_| Ok(()))
                .unwrap()
                .session
                .unwrap()
                .title,
            "First"
        );
        *configured.lock().unwrap() = second.clone();
        let session = provider
            .find("kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Second");
        assert_eq!(session.source_path, source);
        assert_eq!(provider.source_root(), first);
        std::fs::remove_file(second.join("session_index.jsonl")).unwrap();
        assert_ne!(
            provider
                .discover(Window::Created(36500), &mut |_| Ok(()))
                .unwrap()
                .sessions[0]
                .title,
            "Second"
        );
        assert_eq!(
            provider.search_roots().unwrap()[0].1,
            second.join("sessions")
        );
    }

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::providers::source_tests::source_selection(
            "sessions",
            false,
            Codex::new,
            |base| {
                let path = base.join("rollout-kept.jsonl");
                std::fs::create_dir_all(base).unwrap();
                std::fs::write(
                    &path,
                    concat!(
                        r#"{"type":"session_meta","payload":{"id":"kept","#,
                        r#""timestamp":"2026-01-15T00:00:00Z"}}"#,
                        "\n",
                        r#"{"type":"response_item","payload":{"type":"message","#,
                        r#""role":"user","content":[{"type":"input_text","#,
                        r#""text":"Keep"}]}}"#,
                        "\n",
                    ),
                )
                .unwrap();
                path
            },
        );
    }

    #[test]
    fn title_cache_failure_is_recoverable_once_per_operation_and_refreshes() {
        let directory = tempfile::tempdir().unwrap();
        let sessions = directory.path().join("sessions");
        std::fs::create_dir(&sessions).unwrap();
        for id in ["kept", "other"] {
            std::fs::write(
                sessions.join(format!("rollout-{id}.jsonl")),
                serde_json::json!({
                    "type": "session_meta",
                    "payload": {
                        "id": id,
                        "timestamp": "2026-01-15T00:00:00Z",
                        "cwd": "/fallback"
                    }
                })
                .to_string(),
            )
            .unwrap();
        }
        let index = directory.path().join("session_index.jsonl");
        std::fs::create_dir(&index).unwrap();
        let mut provider = Codex::new(SourceRoots::fixed(
            directory.path().into(),
            "sessions",
            "data/codex",
            "CODEX_HOME/sessions",
        ));
        let mut warnings = Vec::new();
        let discovery = provider
            .discover(Window::Created(36500), &mut |warning| {
                warnings.push(warning);
                Ok(())
            })
            .unwrap();
        assert!(discovery.available && discovery.failures.is_empty());
        assert_eq!(discovery.sessions.len(), 2);
        assert!(
            discovery
                .sessions
                .iter()
                .all(|session| session.title == "fallback")
        );
        assert!(matches!(
            warnings.as_slice(),
            [RecoverableDiagnostic::TitleCacheFailed(_)]
        ));

        std::fs::remove_dir(&index).unwrap();
        let updated = b"{\"id\":\"kept\",\"thread_name\":\"Updated\"}\n";
        std::fs::write(&index, updated).unwrap();
        let session = provider
            .find("kept", &mut |_| panic!("healthy index must not warn"))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Updated");
        assert_eq!(std::fs::read(&index).unwrap(), updated);

        std::fs::remove_file(&index).unwrap();
        let discovery = provider
            .discover(Window::Created(36500), &mut |_| {
                panic!("absent index must not warn")
            })
            .unwrap();
        assert!(
            discovery
                .sessions
                .iter()
                .all(|session| session.title == "fallback")
        );
        assert!(!index.exists());
    }

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("sessions/rollout-kept.jsonl");
        std::fs::create_dir(path.parent().unwrap()).unwrap();
        std::fs::write(
            &path,
            "{\"type\":\"session_meta\",\"payload\":{\"id\":\"kept\",\
             \"timestamp\":\"2026-01-15T00:00:00Z\"}}\n",
        )
        .unwrap();
        let provider = Codex::new(SourceRoots::fixed(
            directory.path().into(),
            "sessions",
            "data/codex",
            "CODEX_HOME/sessions",
        ));
        crate::providers::source_tests::removed_file(
            provider,
            &path,
            "kept",
            "CODEX_HOME/sessions",
        );
    }

    fn write(path: &Path, records: &[Value]) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let mut text = records
            .iter()
            .map(Value::to_string)
            .collect::<Vec<_>>()
            .join("\n");
        text.push('\n');
        if rollout::compressed(path) {
            std::fs::write(
                path,
                ruzstd::encoding::compress_to_vec(
                    text.as_bytes(),
                    ruzstd::encoding::CompressionLevel::Fastest,
                ),
            )
            .unwrap();
        } else {
            std::fs::write(path, text).unwrap();
        }
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

    fn time(text: &str) -> Timestamp {
        parse_timestamp(text).unwrap()
    }

    #[test]
    fn discovery_covers_archived_and_compressed_rollouts() {
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path();
        let day = root.join("sessions/2026/01/15");
        write(
            &day.join("rollout-2026-01-15T00-00-00-plain.jsonl"),
            &[meta(
                "plain",
                serde_json::json!({"model_provider": "openai"}),
            )],
        );
        write(
            &day.join("rollout-2026-01-15T00-00-00-plain.jsonl.zst"),
            &[meta("stale", Value::Null)],
        );
        write(
            &day.join("other-ignored.jsonl"),
            &[meta("ignored", Value::Null)],
        );
        write(
            &root.join("archived_sessions/rollout-2026-01-15T00-00-00-archived.jsonl.zst"),
            &[
                meta("archived", Value::Null),
                event(
                    "turn_context",
                    "2026-01-15T00:00:01Z",
                    serde_json::json!({"model": "gpt-5"}),
                ),
                said(
                    "2026-01-15T00:00:02Z",
                    "user",
                    "<environment_context>cwd</environment_context>",
                ),
                said(
                    "2026-01-15T00:00:03Z",
                    "user",
                    "<subagent_notification>{}</subagent_notification>",
                ),
                said("2026-01-15T00:00:04Z", "user", "\n  Fix the parser  \nwith details"),
                said("2026-01-15T00:00:05Z", "assistant", "Done"),
                event(
                    "event_msg",
                    "2026-01-15T00:00:06Z",
                    serde_json::json!({"type": "task_complete"}),
                ),
                event(
                    "event_msg",
                    "2026-01-15T00:00:07Z",
                    serde_json::json!({"type": "thread_settings_applied"}),
                ),
                event(
                    "turn_context",
                    "2026-01-15T00:00:08Z",
                    serde_json::json!({"model": "gpt-5.5"}),
                ),
                said("2026-01-15T00:00:09Z", "developer", "Environment settings"),
            ],
        );
        let mut provider = fixed(root);
        let mut sessions = provider
            .discover(Window::Created(36500), &mut |_| Ok(()))
            .unwrap()
            .sessions;
        sessions.sort_by(|a, b| a.id.cmp(&b.id));
        let ids: Vec<_> =
            sessions.iter().map(|session| &session.id[..]).collect();
        assert_eq!(ids, ["archived", "plain"]);
        let [archived, plain] = &sessions[..] else {
            unreachable!()
        };
        assert_eq!(archived.title, "Fix the parser");
        assert_eq!(archived.updated_at, time("2026-01-15T00:00:06Z"));
        assert_eq!(archived.model, "gpt-5.5");
        assert_eq!(archived.message_count, Some(5));
        assert_eq!((&plain.title[..], &plain.model[..]), ("project", ""));
        let output = tempfile::tempdir().unwrap();
        let exported = crate::output::export::raw(
            "archived",
            &archived.source_path,
            output.path(),
        )
        .unwrap();
        let raw = std::fs::read_to_string(exported).unwrap();
        let first: Value =
            serde_json::from_str(raw.lines().next().unwrap()).unwrap();
        assert_eq!(
            (first["type"].as_str(), raw.lines().count()),
            (Some("session_meta"), 10)
        );
        let data = read(&mut provider, "archived");
        let texts: Vec<_> = data
            .messages
            .iter()
            .map(|message| (&message.role[..], message.parts[0].content()))
            .collect();
        assert_eq!(
            texts,
            [
                (
                    "user",
                    Some("<subagent_notification>{}</subagent_notification>")
                ),
                ("user", Some("\n  Fix the parser\nwith details")),
                ("assistant", Some("Done")),
            ]
        );
    }

    #[test]
    fn large_rollouts_take_activity_and_model_from_the_tail() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory
            .path()
            .join("sessions/rollout-2026-01-15T00-00-00-large.jsonl");
        write(
            &path,
            &[
                meta("large", Value::Null),
                said("2026-01-15T00:00:01Z", "user", "Large"),
                said("2026-01-15T00:00:02Z", "assistant", &"x".repeat(300_000)),
                event(
                    "event_msg",
                    "2026-01-15T00:00:03Z",
                    serde_json::json!({"type": "task_complete"}),
                ),
                event(
                    "turn_context",
                    "2026-01-15T00:00:04Z",
                    serde_json::json!({"model": "late"}),
                ),
                event(
                    "world_state",
                    "2026-01-15T00:00:05Z",
                    serde_json::json!({}),
                ),
            ],
        );
        let session = fixed(directory.path())
            .find("large", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.updated_at, time("2026-01-15T00:00:03Z"));
        assert_eq!(session.model, "late");
        assert_eq!(session.message_count, None);
    }

    #[test]
    fn transcript_items_follow_codex_tool_semantics() {
        let directory = tempfile::tempdir().unwrap();
        let t = "2026-01-15T00:00:01Z";
        write(
            &directory
                .path()
                .join("sessions/rollout-2026-01-15T00-00-00-tools.jsonl"),
            &[
                meta("tools", Value::Null),
                event("turn_context", t, serde_json::json!({"model": "gpt-5"})),
                said(t, "developer", "Hidden instructions"),
                said(t, "system", "Hidden system"),
                said(t, "user", "Please read <instructions>x</instructions>"),
                said(t, "user", "Run it"),
                item(
                    t,
                    serde_json::json!({"type": "reasoning", "summary": [
                        {"type": "summary_text", "text": "first"},
                        {"type": "summary_text", "text": " "},
                        {"type": "summary_text", "text": "second"}
                    ]}),
                ),
                said(
                    t,
                    "assistant",
                    "before <proposed_plan>\nPlan\n</proposed_plan> after",
                ),
                said(t, "user", "PLEASE IMPLEMENT THIS PLAN"),
                item(
                    t,
                    serde_json::json!({
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-1",
                        "arguments": "{\"cmd\":\"ls\"}"
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": "Script completed\nWall time 0.1s\nOutput:\nok"
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "function_call_output",
                        "call_id": "orphan",
                        "output": "dropped"
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "function_call",
                        "name": "create_issue",
                        "namespace": "mcp__codex_apps__github",
                        "call_id": "call-2",
                        "arguments": "{}"
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "custom_tool_call",
                        "name": "exec",
                        "call_id": "exec-1",
                        "input": concat!(
                            "await tools.exec_command({cmd:'pwd'});\n",
                            "await tools.apply_patch('*** Begin Patch\\n",
                            "*** Delete File: a\\n*** End Patch');",
                        )
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "custom_tool_call_output",
                        "call_id": "exec-1",
                        "output": [
                            {
                                "type": "input_text",
                                "text": "Script failed\nWall time 1s\nOutput:\nboom"
                            },
                            {
                                "type": "input_image",
                                "image_url": "data:image/png;base64,AAAA"
                            }
                        ]
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "web_search_call",
                        "status": "completed",
                        "action": {"type": "search", "query": "codex"}
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "tool_search_call",
                        "call_id": "search-1",
                        "arguments": {"query": "sim"}
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "tool_search_output",
                        "call_id": "search-1",
                        "tools": [
                            {
                                "type": "namespace",
                                "name": "mcp__sim__",
                                "tools": [{"name": "boot"}, {"name": "build"}]
                            }
                        ]
                    }),
                ),
                item(
                    t,
                    serde_json::json!({
                        "type": "image_generation_call",
                        "id": "ig_1",
                        "revised_prompt": "A lighthouse",
                        "result": "aW1hZ2U="
                    }),
                ),
            ],
        );
        let data = read(&mut fixed(directory.path()), "tools");
        let parts: Vec<_> = data
            .messages
            .iter()
            .map(|message| serde_json::to_value(&message.parts).unwrap())
            .collect();
        assert_eq!(data.messages[0].role, "user");
        assert_eq!(
            parts[0],
            serde_json::json!([{
                "type": "text",
                "text": "Run it",
                "time_created": time(t).as_millisecond()
            }])
        );
        let assistant = &data.messages[1];
        assert_eq!(assistant.model, Some("gpt-5".into()));
        let kinds: Vec<_> = assistant
            .parts
            .iter()
            .map(|part| match part {
                Part::Reasoning(part) => format!("reasoning:{}", part.text),
                Part::Text(part) => format!("text:{}", part.text),
                Part::Plan(part) => {
                    format!("plan:{}:{}", part.input, part.approval_status)
                }
                _ => "other".into(),
            })
            .collect();
        assert_eq!(
            kinds,
            [
                "reasoning:first\nsecond",
                "text:before",
                "plan:Plan:success",
                "text:after"
            ]
        );
        let tools: Vec<_> = data
            .messages
            .iter()
            .flat_map(|message| &message.parts)
            .filter_map(|part| match part {
                Part::Tool(tool) => Some((
                    &tool.tool[..],
                    &tool.call_id[..],
                    tool.state["status"].as_str().unwrap(),
                    tool.state.get("output").cloned().unwrap_or_default(),
                )),
                _ => None,
            })
            .collect();
        let ms = time(t).as_millisecond();
        assert_eq!(
            tools,
            [
                (
                    "bash",
                    "call-1",
                    "completed",
                    serde_json::json!([{"type": "text", "text": "ok", "time_created": ms}])
                ),
                ("github.create_issue", "call-2", "running", Value::Null),
                (
                    "bash",
                    "exec-1",
                    "error",
                    serde_json::json!([
                        {"type": "text", "text": "boom", "time_created": ms},
                        {
                            "type": "image",
                            "mime_type": "image/png",
                            "data": "AAAA",
                            "time_created": ms
                        }
                    ])
                ),
                ("patch", "exec-1#1", "running", Value::Null),
                ("web_search", "", "completed", Value::Null),
                (
                    "tool_search",
                    "search-1",
                    "completed",
                    serde_json::json!([{
                        "type": "text",
                        "text": "mcp__sim__: boot, build",
                        "time_created": ms
                    }])
                ),
                ("image_generation", "", "completed", Value::Null),
            ]
        );
        assert!(data.messages.iter().all(|message| message.role != "tool"));
    }

    #[test]
    fn token_usage_counts_each_turn_once() {
        let directory = tempfile::tempdir().unwrap();
        let t = "2026-01-15T00:00:01Z";
        let count = |last: u64, total: u64| {
            event(
                "event_msg",
                t,
                serde_json::json!({"type": "token_count", "info": {
                    "total_token_usage": {
                        "input_tokens": total,
                        "cached_input_tokens": total / 2,
                        "total_tokens": total
                    },
                    "last_token_usage": {
                        "input_tokens": last,
                        "cached_input_tokens": last / 2,
                        "total_tokens": last
                    }
                }}),
            )
        };
        let record = |id: &str, input: u64| {
            event(
                "token_usage_record",
                t,
                serde_json::json!({"response_id": id, "usage": {"input_tokens": input}}),
            )
        };
        let compacted = |id: &str| {
            event(
                "compacted",
                t,
                serde_json::json!({"compaction_response_id": id, "replacement_history": []}),
            )
        };
        write(
            &directory
                .path()
                .join("sessions/rollout-2026-01-15T00-00-00-usage.jsonl"),
            &[
                meta("usage", Value::Null),
                said(t, "user", "Count"),
                record("normal", 10),
                count(10, 10),
                count(10, 10),
                record("remote", 50),
                compacted("remote"),
                count(0, 10),
                record("local", 20),
                count(20, 30),
                compacted("local"),
            ],
        );
        let stats = read(&mut fixed(directory.path()), "usage").stats;
        assert_eq!(stats.total_input_tokens, 80.into());
        assert_eq!(stats.extra["total_cache_read_tokens"], 15);
    }

    #[test]
    fn subagents_add_usage_and_missing_replies_to_the_parent() {
        let directory = tempfile::tempdir().unwrap();
        let sessions = directory.path().join("sessions");
        let parent = "019e0000-0000-7000-8000-000000000001";
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
                said("2026-01-15T00:00:03Z", "user", "last"),
                said(
                    "2026-01-15T00:00:04Z",
                    "user",
                    &format!(
                        "<subagent_notification>{}</subagent_notification>",
                        serde_json::json!({
                            "agent_path": "reported",
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
            "019f0000-0000-7000-8000-000000000002",
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
            "reported",
            Value::Null,
            vec![reply(
                "2026-01-15T00:00:04Z",
                "reported result",
                "final_answer",
            )],
        );
        let mut provider = fixed(directory.path());
        let data = read(&mut provider, parent);
        let texts: Vec<_> = data
            .messages
            .iter()
            .map(|message| {
                (
                    message.parts[0].content().unwrap(),
                    message.subagent_id.as_deref(),
                    message.nickname.as_deref(),
                )
            })
            .collect();
        assert_eq!(
            texts,
            [
                ("first", None, None),
                (
                    "child result",
                    Some("019f0000-0000-7000-8000-000000000002"),
                    Some("Pascal")
                ),
                ("last", None, None),
                ("reported result", Some("reported"), None),
            ]
        );
        assert_eq!(data.stats.total_input_tokens, 107.into());
        let child = read(&mut provider, "019f0000-0000-7000-8000-000000000002");
        assert_eq!(child.stats.total_input_tokens, 7.into());
        let session = provider
            .find(parent, &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(provider.change_sources(&session).len(), 3);
    }
}
