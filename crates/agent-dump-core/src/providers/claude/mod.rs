pub(super) mod transcript;

use crate::compat::value::text;
use crate::providers::contract::{
    DiagnosticSink, Provider, RecoverableDiagnostic,
};
use crate::providers::error::LocalizedText;
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::providers::title::{basename, normalize_title};
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, parse_timestamp};
use serde_json::Value;
use std::collections::HashMap;
use std::io::BufRead;
use std::path::{Path, PathBuf};

/// The record fields discovery reads. Content keeps only text items, so tool
/// inputs and results are skipped without being materialized.
#[derive(Default, serde::Deserialize)]
#[serde(default)]
struct Line {
    #[serde(rename = "type")]
    kind: Value,
    #[serde(rename = "isMeta")]
    is_meta: Value,
    timestamp: Value,
    cwd: Value,
    version: Value,
    #[serde(rename = "customTitle")]
    custom_title: Value,
    #[serde(rename = "aiTitle")]
    ai_title: Value,
    message: LineMessage,
}

#[derive(Default, serde::Deserialize)]
#[serde(default)]
struct LineMessage {
    role: Value,
    model: Value,
    content: Content,
}

#[derive(serde::Deserialize)]
struct Item {
    text: Option<Value>,
}

/// Text of a string content, or of the content items carrying `text`.
#[derive(Default)]
struct Content(Option<String>);

impl<'de> serde::Deserialize<'de> for Content {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Content;

            fn expecting(
                &self,
                formatter: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                formatter.write_str("a string or content items")
            }

            fn visit_unit<E>(self) -> Result<Content, E> {
                Ok(Content(None))
            }

            fn visit_str<E>(self, value: &str) -> Result<Content, E> {
                Ok(Content(Some(value.to_owned())))
            }

            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut items: A,
            ) -> Result<Content, A::Error> {
                let mut texts = Vec::new();
                while let Some(item) = items.next_element::<Item>()? {
                    if let Some(Value::String(text)) = item.text {
                        texts.push(text);
                    }
                }
                Ok(Content(Some(texts.join(" "))))
            }
        }
        deserializer.deserialize_any(Visitor)
    }
}

struct Child {
    id: String,
    title: Option<String>,
    tool: Option<String>,
    project: PathBuf,
}

#[derive(Default)]
struct Scan {
    child: Option<Child>,
    created: Option<Timestamp>,
    updated: Option<Timestamp>,
    cwd: Option<String>,
    version: Option<Value>,
    model: String,
    custom_title: Option<String>,
    ai_title: Option<String>,
    prompt_title: Option<String>,
    visible: usize,
}

/// `<session>/subagents` for `subagents/*.jsonl` and for workflow agents in
/// `subagents/workflows/<run>/agent-*.jsonl`.
fn subagents_dir(path: &Path) -> Option<&Path> {
    let directory = path.parent()?;
    if directory.file_name()? == "subagents" {
        return Some(directory);
    }
    let workflows = directory.parent()?;
    let subagents = workflows.parent()?;
    (workflows.file_name()? == "workflows"
        && subagents.file_name()? == "subagents"
        && path.file_name()?.to_string_lossy().starts_with("agent-"))
    .then_some(subagents)
}

fn child(path: &Path) -> Option<Child> {
    let project = subagents_dir(path)?.parent()?.parent()?.to_owned();
    let stem = path.file_stem()?.to_string_lossy();
    let meta: Value =
        std::fs::read(path.with_file_name(format!("{stem}.meta.json")))
            .ok()
            .and_then(|bytes| serde_json::from_slice(&bytes).ok())
            .unwrap_or_default();
    let field = |key: &str| {
        Some(text(&meta[key]).trim())
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
    };
    let id = field("agentId").unwrap_or_else(|| {
        stem.strip_prefix("agent-").unwrap_or(&stem).to_owned()
    });
    (!id.is_empty()).then(|| Child {
        id,
        title: field("name").or_else(|| field("description")),
        tool: field("toolUseId"),
        project,
    })
}

/// Maps the tool calls that started subagents to the subagent session ids.
fn children(path: &Path) -> HashMap<String, String> {
    let root = subagents_dir(path).map_or_else(
        || path.with_extension("").join("subagents"),
        Path::to_owned,
    );
    walkdir::WalkDir::new(root)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.file_type().is_file()
                && entry.path().extension().is_some_and(|ext| ext == "jsonl")
        })
        .filter_map(|entry| child(entry.path()))
        .filter_map(|child| Some((child.tool?, child.id)))
        .collect()
}

fn line(bytes: &[u8]) -> Option<Line> {
    if let Ok(line) = serde_json::from_slice(bytes) {
        return Some(line);
    }
    let record = crate::compat::json::from_slice(bytes)
        .ok()
        .filter(Value::is_object)?;
    let field = |key: &str| record.get(key).cloned().unwrap_or_default();
    let message = &record["message"];
    let content = match &message["content"] {
        Value::String(value) => Some(value.clone()),
        Value::Array(items) => Some(
            items
                .iter()
                .filter_map(|item| item.get("text"))
                .map(text)
                .collect::<Vec<_>>()
                .join(" "),
        ),
        _ => None,
    };
    Some(Line {
        kind: field("type"),
        is_meta: field("isMeta"),
        timestamp: field("timestamp"),
        cwd: field("cwd"),
        version: field("version"),
        custom_title: field("customTitle"),
        ai_title: field("aiTitle"),
        message: LineMessage {
            role: message["role"].clone(),
            model: message["model"].clone(),
            content: Content(content),
        },
    })
}

fn internal(line: &Line) -> bool {
    line.is_meta == true
        || matches!(
            text(&line.kind)
                .trim()
                .to_lowercase()
                .replace(['_', '-'], " ")
                .as_str(),
            "progress"
                | "file history snapshot"
                | "queue operation"
                | "last prompt"
        )
}

pub(super) fn title_line(value: &str) -> Option<String> {
    crate::providers::text::clean(value)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(normalize_title)
}

/// Providers that keep Claude Code's `projects/` transcript layout.
#[derive(Clone, Copy)]
pub enum Kind {
    Claude,
    Qoder,
    QoderCn,
}

impl Kind {
    fn roots(self) -> SourceRoots {
        let (variable, directory, fallback, label) = match self {
            Self::Claude => (
                "CLAUDE_CONFIG_DIR",
                ".claude",
                "data/claudecode",
                "CLAUDE_CONFIG_DIR/projects",
            ),
            Self::Qoder => (
                "QODER_CONFIG_DIR",
                ".qoder",
                "data/qoder",
                "QODER_CONFIG_DIR/projects",
            ),
            Self::QoderCn => (
                "QODERCN_CONFIG_DIR",
                ".qoder-cn",
                "data/qoder-cn",
                "QODERCN_CONFIG_DIR/projects",
            ),
        };
        SourceRoots::new(
            move || file_sessions::environment_root(variable, directory),
            "projects",
            fallback,
            label,
        )
    }

    const fn agent(self) -> &'static str {
        match self {
            Self::Claude => "claude",
            Self::Qoder => "qoder",
            Self::QoderCn => "qoder-cn",
        }
    }

    const fn location_hint(self) -> LocalizedText {
        match self {
            Self::Claude => [
                "Confirm the Claude Code session file is still under the projects directory.",
                "确认 Claude Code 会话文件仍位于 projects 目录下。",
            ],
            Self::Qoder => [
                "Confirm the Qoder session file is still under the projects directory.",
                "确认 Qoder 会话文件仍位于 projects 目录下。",
            ],
            Self::QoderCn => [
                "Confirm the Qoder CN session file is still under the projects directory.",
                "确认 Qoder CN 会话文件仍位于 projects 目录下。",
            ],
        }
    }
}

pub struct Claude {
    kind: Kind,
    roots: SourceRoots,
    titles: HashMap<PathBuf, HashMap<String, Value>>,
}

impl Claude {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open(kind: Kind) -> crate::Result<Self> {
        Ok(Self {
            kind,
            roots: kind.roots(),
            titles: HashMap::new(),
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        let files = self.roots.files(None, |path, base| {
            path.extension().is_some_and(|ext| ext == "jsonl")
                && (path
                    .strip_prefix(base)
                    .is_ok_and(|relative| relative.components().count() == 2)
                    || subagents_dir(path)
                        .and_then(Path::parent)
                        .and_then(Path::parent)
                        .is_some())
        })?;
        if let Some(base) = &self.roots.base {
            crate::storage::source_io::at(base, std::fs::read_dir(base))?;
        }
        Ok(files)
    }

    fn titles(
        &mut self,
        directory: &Path,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<&HashMap<String, Value>> {
        if !self.titles.contains_key(directory) {
            let titles = Self::load_titles(
                &directory.join("sessions-index.json"),
                diagnostics,
            )?;
            self.titles.insert(directory.to_owned(), titles);
        }
        Ok(&self.titles[directory])
    }

    fn load_titles(
        path: &Path,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<HashMap<String, Value>> {
        let mut titles = HashMap::new();
        if !path.exists() {
            return Ok(titles);
        }
        let result = (|| -> crate::Result<Value> {
            let value: Value = crate::compat::json::from_slice(
                &crate::storage::source_io::read(path)?,
            )?;
            if !value.is_object() {
                return Err("sessions index root must be an object".into());
            }
            if value
                .get("entries")
                .is_some_and(|entries| !entries.is_array())
            {
                return Err("sessions index entries must be an array".into());
            }
            Ok(value)
        })();
        let value = match result {
            Ok(value) => value,
            Err(error) => {
                diagnostics(RecoverableDiagnostic::TitleCacheFailed(
                    error.to_string(),
                ))?;
                return Ok(titles);
            }
        };
        let mut skipped = 0;
        for entry in value["entries"].as_array().into_iter().flatten() {
            let id = text(&entry["sessionId"]);
            let summary = &entry["summary"];
            if id.trim().is_empty()
                || !(summary.is_null() || summary.is_string())
            {
                skipped += 1;
                continue;
            }
            titles.insert(id.to_owned(), summary.clone());
        }
        if skipped > 0 {
            diagnostics(RecoverableDiagnostic::TitleCacheEntriesSkipped {
                path: path.to_owned(),
                count: skipped,
            })?;
        }
        Ok(titles)
    }

    fn scan(path: &Path) -> crate::Result<Option<Scan>> {
        let mut reader =
            std::io::BufReader::new(crate::storage::source_io::open(path)?);
        let mut line = Vec::new();
        let mut scan = Scan {
            child: child(path),
            ..Scan::default()
        };
        let mut index = 0;
        loop {
            line.clear();
            if crate::storage::source_io::at(
                path,
                reader.read_until(b'\n', &mut line),
            )? == 0
            {
                break;
            }
            if line.iter().all(u8::is_ascii_whitespace) {
                continue;
            }
            index += 1;
            let Some(record) = self::line(&line) else {
                if index == 1 {
                    return Ok(None);
                }
                continue;
            };
            let timestamp = parse_timestamp(text(&record.timestamp));
            if index == 1 {
                scan.created = timestamp;
            }
            if internal(&record) {
                continue;
            }
            match text(&record.kind) {
                "custom-title" => {
                    if let Some(value) = title_line(text(&record.custom_title))
                    {
                        scan.custom_title = Some(value);
                    }
                    continue;
                }
                "ai-title" => {
                    if let Some(value) = title_line(text(&record.ai_title)) {
                        scan.ai_title = Some(value);
                    }
                    continue;
                }
                _ => {}
            }
            scan.updated = scan.updated.max(timestamp);
            if scan.cwd.is_none() {
                scan.cwd = record
                    .cwd
                    .as_str()
                    .filter(|cwd| !cwd.is_empty())
                    .map(str::to_owned);
            }
            if scan.version.is_none() && !record.version.is_null() {
                scan.version = Some(record.version);
            }
            let message = record.message;
            if scan.model.is_empty() {
                scan.model = text(&message.model).trim().into();
            }
            let role = text(&message.role);
            let prompt = (role == "user")
                .then(|| message.content.0.as_deref().and_then(title_line))
                .flatten();
            if !role.trim().is_empty() && (role != "user" || prompt.is_some()) {
                scan.visible += 1;
            }
            if scan.prompt_title.is_none() && index <= 20 {
                scan.prompt_title = prompt;
            }
        }
        Ok((index > 0).then_some(scan))
    }

    fn parse(
        &mut self,
        path: &Path,
        scan: Option<Scan>,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Option<Session>> {
        let Some(scan) = scan.filter(|scan| scan.visible > 0) else {
            return Ok(None);
        };
        let project = match &scan.child {
            Some(child) => child.project.as_path(),
            None => path.parent().ok_or("Session has no project directory")?,
        };
        let id = scan.child.as_ref().map_or_else(
            || {
                path.file_stem()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into_owned()
            },
            |child| child.id.clone(),
        );
        let created_at = match scan.created {
            Some(created) => created,
            None => Timestamp::try_from(path.metadata()?.modified()?)?,
        };
        let explicit = match scan.child.as_ref().and_then(|c| c.title.clone()) {
            Some(title) => Some(title),
            None => self
                .titles(project, diagnostics)?
                .get(&id)
                .and_then(Value::as_str)
                .map(str::to_owned),
        };
        let directory = scan
            .cwd
            .unwrap_or_else(|| crate::storage::source_io::path_text(project));
        let title = scan
            .custom_title
            .or(scan.ai_title)
            .or_else(|| explicit.as_deref().and_then(title_line))
            .or(scan.prompt_title)
            .or_else(|| basename(&directory))
            .or_else(|| basename(&project.to_string_lossy()))
            .unwrap_or_else(|| "Untitled Session".into());
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at: scan
                .updated
                .map_or(created_at, |updated| updated.max(created_at)),
            subtargets: Vec::new(),
            source_metadata: Value::Null,
            source_path: path.to_owned(),
            directory,
            version: scan.version.unwrap_or_else(|| "".into()),
            model: scan.model,
            project: project
                .file_name()
                .map(|name| name.to_string_lossy().into_owned()),
            message_count: Some(scan.visible),
        }))
    }
}

impl Provider for Claude {
    fn discover(
        &mut self,
        days: Option<i64>,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.titles.clear();
        file_sessions::discover(
            self.files()?,
            days,
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
        self.titles.clear();
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.clone().as_deref(),
            files,
            id,
            |path| {
                path.file_stem().is_some_and(|name| {
                    name == id
                        || name.to_str().and_then(|n| n.strip_prefix("agent-"))
                            == Some(id)
                })
            },
            |path| self.parse(path, Self::scan(path)?, diagnostics),
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            return Err(crate::providers::error::ProviderError::missing(
                ["session source file is missing"; 2],
                &session.source_path,
                Vec::new(),
                crate::providers::contract::source_roots(self)?,
                vec![
                    self.kind.location_hint(),
                    ["Re-run `agent-dump --list` to confirm the session still exists.", "重新运行 `agent-dump --list` 确认该会话是否仍存在。"],
                ],
            ).into());
        }
        crate::providers::claude::transcript::read(
            session,
            self.kind.agent(),
            children(&session.source_path),
            diagnostics,
        )
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

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::providers::source_tests::source_selection(
            "projects",
            true,
            |roots| Claude {
                kind: Kind::Claude,
                roots,
                titles: HashMap::new(),
            },
            |base| {
                let path = base.join("project/kept.jsonl");
                std::fs::create_dir_all(path.parent().unwrap()).unwrap();
                std::fs::write(&path, concat!(r#"{"type":"user","timestamp":"2026-01-15T00:00:00Z","message":{"role":"user","content":"Keep"}}"#, "\n")).unwrap();
                path
            },
        );
    }

    #[test]
    fn title_cache_is_per_project_and_refreshes_after_recovery() {
        let directory = tempfile::tempdir().unwrap();
        let projects = directory.path().join("projects");
        for (project, id) in [
            ("first", "kept"),
            ("first", "other"),
            ("second", "separate"),
        ] {
            let path = projects.join(project).join(format!("{id}.jsonl"));
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(&path, serde_json::json!({"type": "user", "timestamp": "2026-01-15T00:00:00Z", "message": {"role": "user", "content": "Fallback"}}).to_string()).unwrap();
        }
        let index = projects.join("first/sessions-index.json");
        std::fs::write(&index, "[]").unwrap();
        std::fs::write(
            projects.join("second/sessions-index.json"),
            r#"{"entries":[{"sessionId":"separate","summary":"Separate"}]}"#,
        )
        .unwrap();
        let mut provider = Claude {
            kind: Kind::Claude,
            roots: SourceRoots::fixed(
                directory.path().into(),
                "projects",
                "data/claudecode",
                "CLAUDE_CONFIG_DIR/projects",
            ),
            titles: HashMap::new(),
        };
        let mut warnings = Vec::new();
        let discovery = provider
            .discover(Some(36500), &mut |warning| {
                warnings.push(warning);
                Ok(())
            })
            .unwrap();
        assert!(discovery.available && discovery.failures.is_empty());
        assert_eq!(discovery.sessions.len(), 3);
        assert!(
            discovery
                .sessions
                .iter()
                .any(|session| session.title == "Separate")
        );
        assert!(matches!(
            warnings.as_slice(),
            [RecoverableDiagnostic::TitleCacheFailed(_)]
        ));

        let updated =
            r#"{"entries":[{"sessionId":"kept","summary":"Updated"}]}"#;
        std::fs::write(&index, updated).unwrap();
        let session = provider
            .find("kept", &mut |_| panic!("healthy index must not warn"))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Updated");
        assert_eq!(std::fs::read_to_string(&index).unwrap(), updated);

        std::fs::remove_file(&index).unwrap();
        let session = provider
            .find("kept", &mut |_| panic!("absent index must not warn"))
            .unwrap()
            .session
            .unwrap();
        assert_eq!(session.title, "Fallback");
        assert!(!index.exists());
    }

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("projects/project/kept.jsonl");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "{\"type\":\"user\",\"sessionId\":\"kept\",\"timestamp\":\"2026-01-15T00:00:00Z\",\"message\":{\"role\":\"user\",\"content\":\"hello\"}}\n").unwrap();
        let provider = Claude {
            kind: Kind::Claude,
            roots: SourceRoots::fixed(
                directory.path().into(),
                "projects",
                "data/claudecode",
                "CLAUDE_CONFIG_DIR/projects",
            ),
            titles: HashMap::new(),
        };
        crate::providers::source_tests::removed_file(
            provider,
            &path,
            "kept",
            "projects directory",
        );
    }
}
