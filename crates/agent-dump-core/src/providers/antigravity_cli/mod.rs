mod proto;
mod transcript;

use crate::output::formats::OutputFormat;
use crate::providers::contract::{
    DiagnosticSink, Discovery, Lookup, Provider, SessionFailure, Window,
    source_roots,
};
use crate::providers::error::ProviderError;
use crate::providers::files::{self as file_sessions, Located, SourceRoots};
use crate::providers::sqlite::connection::{
    change_sources, connect, has_column, has_table,
};
use crate::session::timestamp::Timestamp;
use crate::session::{Part, Session, SessionData, Stats};
use proto::Message as _;
use rusqlite::Connection;
use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::io::BufRead;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use transcript::Transcript;

const SUMMARIES: &str = "conversation_summaries.db";
const HISTORY: &str = "history.jsonl";

pub struct AntigravityCli {
    roots: SourceRoots,
    profiles: Box<dyn Fn() -> crate::Result<Option<PathBuf>> + Send + Sync>,
}

#[derive(Default)]
pub(super) struct WorkspaceHits {
    pub(super) direct: Vec<usize>,
    pub(super) command: Vec<usize>,
}

impl WorkspaceHits {
    pub(super) fn new(len: usize) -> Self {
        Self {
            direct: vec![0; len],
            command: vec![0; len],
        }
    }
}

struct WorkspaceCandidates {
    raw: Vec<String>,
    normalized: Vec<String>,
}

impl WorkspaceCandidates {
    fn new(raw: Vec<String>) -> Self {
        let normalized = raw
            .iter()
            .map(|candidate| {
                lexical_abs_path(candidate).unwrap_or_else(|| candidate.clone())
            })
            .collect();
        Self { raw, normalized }
    }
}

#[derive(Default)]
struct Summary {
    title: Option<String>,
    workspaces: Vec<String>,
    time: Option<i64>,
    parent: String,
    agent_name: String,
}

struct StoreContext {
    summaries: HashMap<String, Summary>,
    history: HashMap<String, String>,
    files: HashMap<String, PathBuf>,
    resolved: Mutex<HashMap<String, String>>,
}

impl StoreContext {
    fn load(store: &Path, paths: &[PathBuf]) -> crate::Result<Self> {
        let mut files = HashMap::new();
        for path in paths {
            let id = stem(path);
            if !files.contains_key(&id) || path.parent() == Some(store) {
                files.insert(id, path.clone());
            }
        }
        Ok(Self {
            summaries: read_summaries(store)?,
            history: history_workspaces(store)?,
            files,
            resolved: Mutex::new(HashMap::new()),
        })
    }
}

fn stem(path: &Path) -> String {
    path.file_stem()
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned()
}

fn is_windows_root(path: &str) -> bool {
    let bytes = path.as_bytes();
    bytes.len() == 3
        && bytes[0].is_ascii_alphabetic()
        && bytes[1] == b':'
        && matches!(bytes[2], b'/' | b'\\')
}

fn is_windows_path(path: &str) -> bool {
    let bytes = path.as_bytes();
    path.starts_with("\\\\")
        || (bytes.get(1) == Some(&b':')
            && matches!(bytes.get(2), Some(b'/' | b'\\')))
}

fn workspace_paths(uris: impl IntoIterator<Item = String>) -> Vec<String> {
    let mut paths = Vec::new();
    let mut seen = HashSet::new();
    for uri in uris {
        let Some(path) = url::Url::parse(&uri)
            .ok()
            .and_then(|url| url.to_file_path().ok())
        else {
            continue;
        };
        let mut value = crate::storage::source_io::path_text(&path);
        while value.len() > 1
            && value.ends_with(['/', '\\'])
            && !is_windows_root(&value)
        {
            value.pop();
        }
        if !value.is_empty() && seen.insert(value.clone()) {
            paths.push(value);
        }
    }
    paths
}

fn normalize_abs_path(path: &str) -> String {
    let win = is_windows_path(path);
    let value = if win {
        path.replace('\\', "/")
    } else {
        path.to_owned()
    };
    let (prefix, rest) = if win && value.starts_with("//") {
        let mut parts = value[2..].splitn(3, '/');
        (
            format!(
                "//{}/{}",
                parts.next().unwrap_or(""),
                parts.next().unwrap_or("")
            ),
            parts.next().unwrap_or(""),
        )
    } else if win && value.as_bytes().get(1) == Some(&b':') {
        (value[..2].to_owned(), value[2..].trim_start_matches('/'))
    } else {
        (String::new(), value.trim_start_matches('/'))
    };
    let mut parts = Vec::new();
    for part in rest.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            _ => parts.push(part),
        }
    }
    let result = format!("{prefix}/{}", parts.join("/"));
    if win {
        result.replace('/', "\\")
    } else {
        result
    }
}

fn lexical_abs_path(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    let path = if trimmed.starts_with("file://") {
        let path = url::Url::parse(trimmed).ok()?.to_file_path().ok()?;
        crate::storage::source_io::path_text(&path)
    } else if trimmed.starts_with('/') || is_windows_path(trimmed) {
        trimmed.to_owned()
    } else {
        return None;
    };
    Some(normalize_abs_path(&path))
}

fn match_candidate(raw: &str, candidates: &[String]) -> Option<usize> {
    let path = lexical_abs_path(raw)?;
    candidates
        .iter()
        .enumerate()
        .filter(|(_, cand)| {
            !cand.is_empty()
                && (path == **cand
                    || path
                        .strip_prefix(cand.as_str())
                        .is_some_and(|rest| rest.starts_with(['/', '\\']))
                    || (cand.ends_with(['/', '\\'])
                        && path.starts_with(cand.as_str())))
        })
        .min_by(|(left_idx, left), (right_idx, right)| {
            right
                .len()
                .cmp(&left.len())
                .then_with(|| left_idx.cmp(right_idx))
        })
        .map(|(idx, _)| idx)
}

pub(super) fn record_user_context(
    user: &proto::UserPrompt,
    candidates: &[String],
    direct: &mut [usize],
) {
    for item in &user.items {
        if let Some(context) = &item.context {
            for uri in [&context.file, &context.directory]
                .into_iter()
                .flatten()
                .filter_map(|target| target.uri.as_deref())
            {
                if let Some(idx) = match_candidate(uri, candidates) {
                    direct[idx] += 1;
                }
            }
        }
    }
}

pub(super) fn record_tool_input(
    value: &Value,
    candidates: &[String],
    hits: &mut WorkspaceHits,
) {
    record_tool_input_node(value, "", 0, candidates, hits);
}

fn record_tool_input_node(
    value: &Value,
    key: &str,
    depth: usize,
    candidates: &[String],
    hits: &mut WorkspaceHits,
) {
    if depth > 4 {
        return;
    }
    match value {
        Value::Object(map) => {
            for (child_key, child) in map {
                record_tool_input_node(
                    child,
                    child_key,
                    depth + 1,
                    candidates,
                    hits,
                );
            }
        }
        Value::Array(items) => {
            for item in items {
                record_tool_input_node(item, key, depth + 1, candidates, hits);
            }
        }
        Value::String(text) => {
            let lower = key.trim().to_ascii_lowercase();
            if lower.contains("command") {
                record_command_hits(text, candidates, &mut hits.command);
            } else if (lower.contains("path")
                || lower.contains("file")
                || lower.contains("dir")
                || matches!(lower.as_str(), "cwd" | "workdir"))
                && let Some(idx) = match_candidate(text, candidates)
            {
                hits.direct[idx] += 1;
            }
        }
        _ => {}
    }
}

fn record_command_hits(
    text: &str,
    candidates: &[String],
    command: &mut [usize],
) {
    let mut order: Vec<usize> = (0..candidates.len())
        .filter(|&i| !candidates[i].is_empty())
        .collect();
    order.sort_by(|&a, &b| {
        candidates[b]
            .len()
            .cmp(&candidates[a].len())
            .then_with(|| a.cmp(&b))
    });
    let mut matched_spans: Vec<(usize, usize)> = Vec::new();
    let bytes = text.as_bytes();
    for idx in order {
        let cand = &candidates[idx];
        let mut search_from = 0;
        while let Some(rel) = text[search_from..].find(cand.as_str()) {
            let start = search_from + rel;
            let end = start + cand.len();
            let overlaps =
                matched_spans.iter().any(|&(s, e)| start < e && end > s);
            let left_ok = start == 0
                || b" \t\r\n\"'=:;([".contains(&bytes[start - 1])
                || text[..start].ends_with("file://");
            let right_ok = end == text.len()
                || b"/\\ \t\r\n\"';&|)]:".contains(&bytes[end]);
            if !overlaps && left_ok && right_ok {
                command[idx] += 1;
                matched_spans.push((start, end));
                search_from = end;
            } else {
                search_from = start
                    + text[start..].chars().next().map_or(1, char::len_utf8);
            }
        }
    }
}

fn unique_winner(scores: &[usize]) -> Option<usize> {
    let best = *scores.iter().max()?;
    if best == 0 {
        return None;
    }
    let mut winner = None;
    for (idx, &score) in scores.iter().enumerate() {
        if score == best {
            if winner.is_some() {
                return None;
            }
            winner = Some(idx);
        }
    }
    winner
}

fn history_workspaces(
    conversations: &Path,
) -> crate::Result<HashMap<String, String>> {
    let path = conversations
        .parent()
        .unwrap_or(conversations)
        .join(HISTORY);
    let file = match std::fs::File::open(&path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(HashMap::new());
        }
        Err(error) => return Err(error.into()),
    };
    let mut workspaces = HashMap::new();
    for line in std::io::BufReader::new(file).lines() {
        let Ok(line) = line else {
            continue;
        };
        let Ok(value) = serde_json::from_str::<Value>(&line) else {
            continue;
        };
        if let (Some(id), Some(workspace)) = (
            value["conversationId"].as_str().filter(|s| !s.is_empty()),
            value["workspace"].as_str().filter(|s| !s.is_empty()),
        ) {
            workspaces.insert(id.to_owned(), workspace.to_owned());
        }
    }
    Ok(workspaces)
}

fn read_summaries(
    conversations: &Path,
) -> crate::Result<HashMap<String, Summary>> {
    let mut summaries = HashMap::new();
    let path = conversations
        .parent()
        .unwrap_or(conversations)
        .join(SUMMARIES);
    if !path.is_file() {
        return Ok(summaries);
    }
    let connection = connect(&path)?;
    let parent = if has_column(
        &connection,
        "conversation_summaries",
        "parent_conversation_id",
    )? {
        "parent_conversation_id"
    } else {
        "NULL"
    };
    let agent_name =
        if has_column(&connection, "conversation_summaries", "agent_name")? {
            "agent_name"
        } else {
            "NULL"
        };
    let sql = format!(
        "SELECT conversation_id, title, workspace_uris, last_modified_time, \
         {parent}, {agent_name} FROM conversation_summaries"
    );
    let mut statement = connection.prepare(&sql)?;
    let mut rows = statement.query([])?;
    while let Some(row) = rows.next()? {
        let modified = row.get::<_, Option<String>>(3)?;
        summaries.insert(
            row.get(0)?,
            Summary {
                title: row.get(1)?,
                workspaces: row
                    .get::<_, Option<String>>(2)?
                    .as_deref()
                    .and_then(|uris| {
                        serde_json::from_str::<Vec<String>>(uris).ok()
                    })
                    .map(workspace_paths)
                    .unwrap_or_default(),
                time: modified
                    .and_then(|time| time.replacen(' ', "T", 1).parse().ok())
                    .map(Timestamp::as_millisecond),
                parent: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                agent_name: row
                    .get::<_, Option<String>>(5)?
                    .unwrap_or_default(),
            },
        );
    }
    Ok(summaries)
}

fn timestamp(milliseconds: i64) -> crate::Result<Timestamp> {
    Timestamp::from_microsecond(
        milliseconds
            .checked_mul(1000)
            .ok_or("Antigravity CLI time is out of range")?,
    )
}

fn load(
    connection: &Connection,
    id: &str,
    fallback: i64,
    candidates: &[String],
) -> crate::Result<Option<Transcript>> {
    let mut transcript =
        transcript::read(connection, id, fallback, candidates)?;
    if transcript.messages.is_empty() && transcript.unsupported == 0 {
        return Ok(None);
    }
    crate::providers::text::clean_messages(&mut transcript.messages);
    Ok(Some(transcript))
}

fn trajectory_workspaces(
    connection: &Connection,
) -> crate::Result<Vec<String>> {
    if !has_table(connection, "trajectory_metadata_blob")? {
        return Ok(Vec::new());
    }
    let mut statement =
        connection.prepare("SELECT data FROM trajectory_metadata_blob")?;
    let mut rows = statement.query([])?;
    while let Some(row) = rows.next()? {
        let metadata =
            proto::TrajectoryMetadata::decode(&row.get::<_, Vec<u8>>(0)?)
                .map_err(|error| {
                    format!(
                        "invalid Antigravity CLI workspace metadata: {error}"
                    )
                })?;
        let directories = workspace_paths(metadata.workspaces);
        if !directories.is_empty() {
            return Ok(directories);
        }
    }
    Ok(Vec::new())
}

fn resolve_directory(
    id: &str,
    parent: &str,
    candidates: &WorkspaceCandidates,
    hits: &WorkspaceHits,
    ctx: &StoreContext,
    visited: &mut HashSet<String>,
) -> crate::Result<String> {
    if candidates.raw.is_empty() {
        return Ok(String::new());
    }
    if candidates.raw.len() == 1 {
        return Ok(candidates.raw[0].clone());
    }
    if let Some(idx) = ctx
        .history
        .get(id)
        .and_then(|ws| match_candidate(ws, &candidates.normalized))
    {
        return Ok(candidates.raw[idx].clone());
    }
    if let Some(idx) = unique_winner(&hits.direct) {
        return Ok(candidates.raw[idx].clone());
    }
    if let Some(idx) = unique_winner(&hits.command) {
        return Ok(candidates.raw[idx].clone());
    }
    if !parent.is_empty() && parent != id {
        if let Some(idx) = ctx
            .history
            .get(parent)
            .and_then(|ws| match_candidate(ws, &candidates.normalized))
        {
            return Ok(candidates.raw[idx].clone());
        }
        if let Some(parent_dir) =
            resolve_parent_directory(parent, ctx, visited)?
            && let Some(idx) =
                match_candidate(&parent_dir, &candidates.normalized)
        {
            return Ok(candidates.raw[idx].clone());
        }
    }
    Ok(candidates.raw[0].clone())
}

fn resolve_parent_directory(
    parent_id: &str,
    ctx: &StoreContext,
    visited: &mut HashSet<String>,
) -> crate::Result<Option<String>> {
    let cached = ctx.resolved.lock().unwrap().get(parent_id).cloned();
    if let Some(dir) = cached {
        return Ok(Some(dir));
    }
    if !visited.insert(parent_id.to_owned()) {
        return Ok(None);
    }
    let result = resolve_uncached_directory(parent_id, ctx, visited);
    visited.remove(parent_id);
    let directory = result?;
    if let Some(directory) = &directory {
        ctx.resolved
            .lock()
            .unwrap()
            .insert(parent_id.to_owned(), directory.clone());
    }
    Ok(directory)
}

fn resolve_uncached_directory(
    parent_id: &str,
    ctx: &StoreContext,
    visited: &mut HashSet<String>,
) -> crate::Result<Option<String>> {
    let Some(path) = ctx.files.get(parent_id) else {
        return Ok(None);
    };
    let summary = ctx.summaries.get(parent_id);
    let mut raw = summary
        .map(|summary| summary.workspaces.clone())
        .unwrap_or_default();
    let connection = connect(path)?;
    if raw.is_empty() {
        raw = trajectory_workspaces(&connection)?;
    }
    if raw.len() <= 1 {
        return Ok(Some(raw.into_iter().next().unwrap_or_default()));
    }
    let candidates = WorkspaceCandidates::new(raw);
    if let Some(idx) = ctx
        .history
        .get(parent_id)
        .and_then(|ws| match_candidate(ws, &candidates.normalized))
    {
        return Ok(Some(candidates.raw[idx].clone()));
    }
    let hits = transcript::workspace_hits(&connection, &candidates.normalized)?;
    let parent = summary.map_or("", |summary| summary.parent.as_str());
    resolve_directory(parent_id, parent, &candidates, &hits, ctx, visited)
        .map(Some)
}

fn session(path: &Path, ctx: &StoreContext) -> crate::Result<Option<Session>> {
    let id = stem(path);
    let summary = ctx.summaries.get(&id);
    let fallback = match summary.and_then(|summary| summary.time) {
        Some(time) => time,
        None => {
            Timestamp::try_from(path.metadata()?.modified()?)?.as_millisecond()
        }
    };
    let connection = connect(path)?;
    let mut raw = summary
        .map(|summary| summary.workspaces.clone())
        .unwrap_or_default();
    if raw.is_empty() {
        raw = trajectory_workspaces(&connection)?;
    }
    let candidates = WorkspaceCandidates::new(raw);
    let match_candidates = if candidates.normalized.len() > 1 {
        candidates.normalized.as_slice()
    } else {
        &[]
    };
    let Some(transcript) = load(&connection, &id, fallback, match_candidates)?
    else {
        return Ok(None);
    };
    let directory = if candidates.raw.len() <= 1 {
        candidates.raw.into_iter().next().unwrap_or_default()
    } else {
        let mut visited = HashSet::from([id.clone()]);
        let parent = summary.map_or("", |summary| summary.parent.as_str());
        let resolved = resolve_directory(
            &id,
            parent,
            &candidates,
            &transcript.hits,
            ctx,
            &mut visited,
        )?;
        ctx.resolved
            .lock()
            .unwrap()
            .insert(id.clone(), resolved.clone());
        resolved
    };
    let agent_name = summary
        .filter(|summary| !summary.parent.is_empty() && summary.parent != id)
        .map(|summary| summary.agent_name.as_str())
        .filter(|name| !name.is_empty());
    let prompt = transcript
        .messages
        .iter()
        .find(|message| message.role == "user")
        .and_then(|message| message.parts.first())
        .and_then(Part::content);
    let title = [
        transcript.title.as_deref(),
        summary.and_then(|summary| summary.title.as_deref()),
        agent_name,
        prompt,
    ]
    .into_iter()
    .flatten()
    .find_map(crate::providers::kimi::title)
    .unwrap_or_else(|| "Untitled Session".into());
    let times = transcript
        .messages
        .iter()
        .map(|message| message.time_created);
    let created = timestamp(times.clone().fold(fallback, i64::min))?;
    let updated = timestamp(times.fold(fallback, i64::max))?;
    Ok(Some(Session {
        directory,
        model: transcript.model.unwrap_or_default(),
        message_count: Some(transcript.messages.len()),
        source_metadata: serde_json::json!({ "fallback_time": fallback }),
        ..Session::new(id, title, path.to_owned(), created, updated)
    }))
}

impl AntigravityCli {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::located(
                || {
                    let sessions = match file_sessions::environment_path(
                        "AGY_CONVERSATIONS_DIR",
                    )? {
                        Some(path) => path,
                        None => file_sessions::environment_root(
                            "HOME",
                            ".gemini/antigravity-cli",
                        )?
                        .join("conversations"),
                    };
                    Ok(Located {
                        owner: sessions
                            .parent()
                            .filter(|owner| !owner.as_os_str().is_empty())
                            .unwrap_or(&sessions)
                            .to_owned(),
                        sessions,
                        label: "AGY_CONVERSATIONS_DIR",
                    })
                },
                "data/antigravity-cli/conversations",
            ),
            profiles: Box::new(|| {
                if file_sessions::environment_value("AGY_CONVERSATIONS_DIR")
                    .is_some()
                {
                    return Ok(None);
                }
                Ok(Some(
                    file_sessions::environment_root("T3CODE_HOME", ".t3")?
                        .join("userdata/providers/antigravity"),
                ))
            }),
        })
    }

    fn stores(&mut self) -> crate::Result<(Vec<PathBuf>, Vec<SessionFailure>)> {
        self.roots.select()?;
        let mut stores: Vec<_> = self.roots.base.clone().into_iter().collect();
        let mut failures = Vec::new();
        if let Some(profiles) = (self.profiles)()? {
            let entries = match std::fs::read_dir(&profiles) {
                Ok(entries) => entries,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                    return Ok((stores, failures));
                }
                Err(error) => {
                    failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(&profiles),
                        error: error.into(),
                    });
                    return Ok((stores, failures));
                }
            };
            for entry in entries {
                match entry.and_then(|entry| {
                    Ok(entry.file_type()?.is_dir().then(|| {
                        entry.path().join("antigravity-acp/conversations")
                    }))
                }) {
                    Ok(Some(path)) => stores.push(path),
                    Ok(None) => {}
                    Err(error) => failures.push(SessionFailure {
                        source: crate::storage::source_io::path_text(&profiles),
                        error: error.into(),
                    }),
                }
            }
        }
        stores.sort();
        Ok((stores, failures))
    }

    fn missing(&self, path: &Path) -> crate::Result<crate::Error> {
        Ok(ProviderError::missing(
            ["session source file is missing"; 2],
            path,
            Vec::new(),
            source_roots(self)?,
            vec![
                [
                    "Confirm the Antigravity CLI conversation database has \
                     not been moved or cleaned up.",
                    "确认 Antigravity CLI 会话数据库没有被移动或清理。",
                ],
                [
                    "Re-run `agent-dump --list` to check whether the session is still visible.",
                    "重新运行 `agent-dump --list` 检查该会话是否仍可见。",
                ],
            ],
        )
        .into())
    }
}

impl Provider for AntigravityCli {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Discovery> {
        let (stores, failures) = self.stores()?;
        let mut discovery = Discovery {
            failures,
            ..Discovery::default()
        };
        for store in stores {
            let result = (|| {
                let files = file_sessions::files(&store, None, |path, _| {
                    path.extension().is_some_and(|extension| extension == "db")
                })?;
                let context = StoreContext::load(&store, &files.paths)?;
                // Native step times can be newer than a WAL database's file time.
                file_sessions::discover(
                    files,
                    window,
                    false,
                    |path| session(path, &context),
                    |_, session, _| Ok(session),
                )
            })();
            match result {
                Ok(found) => {
                    discovery.available |= found.available;
                    discovery.sessions.extend(found.sessions);
                    discovery.failures.extend(found.failures);
                }
                Err(error) => discovery.failures.push(SessionFailure {
                    source: crate::storage::source_io::path_text(&store),
                    error,
                }),
            }
        }
        discovery
            .sessions
            .sort_by(|a, b| b.created_at.cmp(&a.created_at));
        Ok(discovery)
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Lookup> {
        let (stores, failures) = self.stores()?;
        let mut lookup = Lookup {
            failures,
            ..Lookup::default()
        };
        for store in stores {
            let result = (|| {
                let files = file_sessions::files(&store, None, |path, _| {
                    path.extension().is_some_and(|extension| extension == "db")
                })?;
                let context = StoreContext::load(&store, &files.paths)?;
                file_sessions::find(
                    Some(&store),
                    files,
                    id,
                    |path| stem(path) == id,
                    |path| session(path, &context),
                )
            })();
            match result {
                Ok(found) => {
                    lookup.failures.extend(found.failures);
                    if found.session.is_some() {
                        lookup.session = found.session;
                        break;
                    }
                }
                Err(error) => lookup.failures.push(SessionFailure {
                    source: crate::storage::source_io::path_text(&store),
                    error,
                }),
            }
        }
        Ok(lookup)
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let path = &session.source_path;
        if !path.is_file() {
            return Err(self.missing(path)?);
        }
        let fallback = session.source_metadata["fallback_time"]
            .as_i64()
            .unwrap_or_else(|| session.updated_at.as_millisecond());
        let transcript = load(&connect(path)?, &session.id, fallback, &[])?
            .unwrap_or_default();
        let stats = Stats {
            message_count: transcript.messages.len(),
            total_input_tokens: transcript.input.into(),
            total_output_tokens: transcript.output.into(),
            total_tokens: transcript.total.map(Into::into),
            ..Stats::default()
        };
        Ok(session.payload(transcript.messages, stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        let mut roots = self.roots.search_roots()?;
        if let Some(profiles) = (self.profiles)()? {
            roots.push(("T3CODE_HOME", profiles));
        }
        Ok(roots)
    }

    fn protected_roots(&mut self) -> crate::Result<Vec<PathBuf>> {
        let mut roots: Vec<_> = self
            .roots
            .select()?
            .into_iter()
            .map(Path::to_owned)
            .collect();
        if let Some(profiles) = (self.profiles)()? {
            roots.push(profiles);
        }
        Ok(roots)
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        change_sources(&session.source_path)
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }

    fn supports_format(&self, format: OutputFormat) -> bool {
        format != OutputFormat::Raw
    }
}

#[cfg(test)]
mod tests;
