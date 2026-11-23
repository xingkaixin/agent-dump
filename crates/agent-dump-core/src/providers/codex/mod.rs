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

#[derive(Default)]
struct FastPayload<'a> {
    kind: Option<std::borrow::Cow<'a, str>>,
    unhashable_kind: Option<&'static str>,
    role: Option<std::borrow::Cow<'a, str>>,
    model: Option<std::borrow::Cow<'a, str>>,
    timestamp: Option<std::borrow::Cow<'a, str>>,
}

#[derive(Default)]
struct FastRecord<'a> {
    kind: Option<std::borrow::Cow<'a, str>>,
    timestamp: Option<std::borrow::Cow<'a, str>>,
    payload: FastPayload<'a>,
}

struct CowStrVisitor;

impl<'de> serde::de::Visitor<'de> for CowStrVisitor {
    type Value = Option<std::borrow::Cow<'de, str>>;

    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("any JSON value")
    }

    fn visit_borrowed_str<E>(self, v: &'de str) -> Result<Self::Value, E> {
        Ok(Some(std::borrow::Cow::Borrowed(v)))
    }

    fn visit_str<E>(self, v: &str) -> Result<Self::Value, E> {
        Ok(Some(std::borrow::Cow::Owned(v.to_owned())))
    }

    fn visit_string<E>(self, v: String) -> Result<Self::Value, E> {
        Ok(Some(std::borrow::Cow::Owned(v)))
    }

    fn visit_bool<E>(self, _: bool) -> Result<Self::Value, E> {
        Ok(None)
    }

    fn visit_i64<E>(self, _: i64) -> Result<Self::Value, E> {
        Ok(None)
    }

    fn visit_u64<E>(self, _: u64) -> Result<Self::Value, E> {
        Ok(None)
    }

    fn visit_f64<E>(self, _: f64) -> Result<Self::Value, E> {
        Ok(None)
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(None)
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(None)
    }

    fn visit_seq<A: serde::de::SeqAccess<'de>>(
        self,
        mut seq: A,
    ) -> Result<Self::Value, A::Error> {
        while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
        Ok(None)
    }

    fn visit_map<A: serde::de::MapAccess<'de>>(
        self,
        mut map: A,
    ) -> Result<Self::Value, A::Error> {
        while map
            .next_entry::<serde::de::IgnoredAny, serde::de::IgnoredAny>()?
            .is_some()
        {}
        Ok(None)
    }
}

struct PayloadTypeVisitor;

enum PayloadType<'a> {
    Str(std::borrow::Cow<'a, str>),
    Unhashable(&'static str),
    Other,
}

impl<'de> serde::de::Visitor<'de> for PayloadTypeVisitor {
    type Value = PayloadType<'de>;

    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("any JSON value")
    }

    fn visit_borrowed_str<E>(self, v: &'de str) -> Result<Self::Value, E> {
        Ok(PayloadType::Str(std::borrow::Cow::Borrowed(v)))
    }

    fn visit_str<E>(self, v: &str) -> Result<Self::Value, E> {
        Ok(PayloadType::Str(std::borrow::Cow::Owned(v.to_owned())))
    }

    fn visit_string<E>(self, v: String) -> Result<Self::Value, E> {
        Ok(PayloadType::Str(std::borrow::Cow::Owned(v)))
    }

    fn visit_bool<E>(self, _: bool) -> Result<Self::Value, E> {
        Ok(PayloadType::Other)
    }

    fn visit_i64<E>(self, _: i64) -> Result<Self::Value, E> {
        Ok(PayloadType::Other)
    }

    fn visit_u64<E>(self, _: u64) -> Result<Self::Value, E> {
        Ok(PayloadType::Other)
    }

    fn visit_f64<E>(self, _: f64) -> Result<Self::Value, E> {
        Ok(PayloadType::Other)
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(PayloadType::Other)
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(PayloadType::Other)
    }

    fn visit_seq<A: serde::de::SeqAccess<'de>>(
        self,
        mut seq: A,
    ) -> Result<Self::Value, A::Error> {
        while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
        Ok(PayloadType::Unhashable("list"))
    }

    fn visit_map<A: serde::de::MapAccess<'de>>(
        self,
        mut map: A,
    ) -> Result<Self::Value, A::Error> {
        let mut is_number = false;
        let mut entries = 0usize;
        while let Some(key) = map.next_key::<std::borrow::Cow<'de, str>>()? {
            entries += 1;
            is_number = entries == 1 && key == "$serde_json::private::Number";
            map.next_value::<serde::de::IgnoredAny>()?;
        }
        if is_number {
            Ok(PayloadType::Other)
        } else {
            Ok(PayloadType::Unhashable("dict"))
        }
    }
}

struct CowStrSeed;
impl<'de> serde::de::DeserializeSeed<'de> for CowStrSeed {
    type Value = Option<std::borrow::Cow<'de, str>>;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Self::Value, D::Error> {
        deserializer.deserialize_any(CowStrVisitor)
    }
}

struct PayloadTypeSeed;
impl<'de> serde::de::DeserializeSeed<'de> for PayloadTypeSeed {
    type Value = PayloadType<'de>;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Self::Value, D::Error> {
        deserializer.deserialize_any(PayloadTypeVisitor)
    }
}

struct FastPayloadSeed;
impl<'de> serde::de::DeserializeSeed<'de> for FastPayloadSeed {
    type Value = FastPayload<'de>;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Self::Value, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = FastPayload<'de>;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Self::Value, A::Error> {
                let mut out = FastPayload::default();
                while let Some(key) =
                    map.next_key::<std::borrow::Cow<'de, str>>()?
                {
                    match key.as_ref() {
                        "type" => match map.next_value_seed(PayloadTypeSeed)? {
                            PayloadType::Str(s) => {
                                out.kind = Some(s);
                                out.unhashable_kind = None;
                            }
                            PayloadType::Unhashable(name) => {
                                out.kind = None;
                                out.unhashable_kind = Some(name);
                            }
                            PayloadType::Other => {
                                out.kind = None;
                                out.unhashable_kind = None;
                            }
                        },
                        "role" => out.role = map.next_value_seed(CowStrSeed)?,
                        "model" => {
                            out.model = map.next_value_seed(CowStrSeed)?;
                        }
                        "timestamp" => {
                            out.timestamp = map.next_value_seed(CowStrSeed)?;
                        }
                        _ => {
                            map.next_value::<serde::de::IgnoredAny>()?;
                        }
                    }
                }
                Ok(out)
            }
            fn visit_bool<E>(self, _: bool) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_i64<E>(self, _: i64) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_u64<E>(self, _: u64) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_f64<E>(self, _: f64) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_str<E>(self, _: &str) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_unit<E>(self) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_none<E>(self) -> Result<Self::Value, E> {
                Ok(FastPayload::default())
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<Self::Value, A::Error> {
                while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
                Ok(FastPayload::default())
            }
        }
        deserializer.deserialize_any(V)
    }
}

fn parse_fast_record(line: &[u8]) -> Option<FastRecord<'_>> {
    struct V;
    impl<'de> serde::de::Visitor<'de> for V {
        type Value = FastRecord<'de>;
        fn expecting(
            &self,
            f: &mut std::fmt::Formatter<'_>,
        ) -> std::fmt::Result {
            f.write_str("a JSON object")
        }
        fn visit_map<A: serde::de::MapAccess<'de>>(
            self,
            mut map: A,
        ) -> Result<Self::Value, A::Error> {
            let mut out = FastRecord::default();
            while let Some(key) =
                map.next_key::<std::borrow::Cow<'de, str>>()?
            {
                match key.as_ref() {
                    "type" => out.kind = map.next_value_seed(CowStrSeed)?,
                    "timestamp" => {
                        out.timestamp = map.next_value_seed(CowStrSeed)?;
                    }
                    "payload" => {
                        out.payload = map.next_value_seed(FastPayloadSeed)?;
                    }
                    _ => {
                        map.next_value::<serde::de::IgnoredAny>()?;
                    }
                }
            }
            Ok(out)
        }
    }
    let text = std::str::from_utf8(line).ok()?;
    let text = text.trim_start_matches([' ', '\t', '\n', '\r']);
    if !text.starts_with('{') {
        return None;
    }
    let mut de = serde_json::Deserializer::from_str(text);
    let record = serde::Deserializer::deserialize_map(&mut de, V).ok()?;
    de.end().ok()?;
    Some(record)
}

impl FastRecord<'_> {
    fn active(&self) -> bool {
        match self.kind.as_deref().unwrap_or("") {
            "response_item" => match self.payload.kind.as_deref().unwrap_or("")
            {
                "message" => matches!(
                    self.payload.role.as_deref().unwrap_or(""),
                    "user" | "assistant"
                ),
                "reasoning"
                | "function_call"
                | "function_call_output"
                | "custom_tool_call"
                | "custom_tool_call_output" => true,
                _ => false,
            },
            "event_msg" => matches!(
                self.payload.kind.as_deref().unwrap_or(""),
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

    fn time(&self) -> Option<Timestamp> {
        let a = self
            .timestamp
            .as_deref()
            .and_then(|s| parse_timestamp(s.trim()));
        let b = self
            .payload
            .timestamp
            .as_deref()
            .and_then(|s| parse_timestamp(s.trim()));
        a.max(b)
    }

    fn meta_model(&self) -> Option<String> {
        if !matches!(
            self.kind.as_deref().unwrap_or(""),
            "session_meta" | "turn_context"
        ) {
            return None;
        }
        let model = self.payload.model.as_deref().unwrap_or("").trim();
        (!model.is_empty()).then(|| model.to_owned())
    }
}

impl Activity {
    fn visit_fast(&mut self, record: &FastRecord<'_>) -> crate::Result<()> {
        if let Some(kind) = record.payload.unhashable_kind {
            return Err(format!("unhashable type: '{kind}'").into());
        }
        if record.active()
            && let Some(time) = record.time()
        {
            self.updated = self.updated.max(Some(time));
        }
        if let Some(model) = record.meta_model() {
            self.model = Some(model);
        }
        if record.kind.as_deref() == Some("response_item")
            && matches!(
                record.payload.kind.as_deref().unwrap_or(""),
                "message" | "function_call" | "function_call_output"
            )
        {
            self.count += 1;
        }
        Ok(())
    }

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

fn visit_recent_line(
    line: &[u8],
    recent: &mut Activity,
    last: &mut Option<Timestamp>,
) -> bool {
    if !line.iter().any(|b| !b.is_ascii_whitespace()) {
        return false;
    }
    if let Some(record) = parse_fast_record(line) {
        *last = (*last).or_else(|| record.time());
        if recent.model.is_none() {
            recent.model = record.meta_model();
        }
        if record.active()
            && let Some(time) = record.time()
        {
            recent.updated = Some(time);
            return true;
        }
        return false;
    }
    let Some(record) = rollout::object(line) else {
        return false;
    };
    *last = (*last).or_else(|| record_time(&record));
    if recent.model.is_none() {
        recent.model = meta_model(&record);
    }
    if active(&record)
        && let Some(time) = record_time(&record)
    {
        recent.updated = Some(time);
        return true;
    }
    false
}

/// Reopening a rollout appends settings records; the last activity
/// before them is usually within the final window.
fn recent(
    path: &Path,
    file: &mut std::fs::File,
    size: u64,
) -> crate::Result<(Activity, Option<Timestamp>)> {
    let floor = size.saturating_sub(TAIL_LIMIT);
    let mut recent = Activity::default();
    let mut last = None;
    let mut buf = vec![0u8; usize::try_from(TAIL_WINDOW)?];
    let mut scratch = Vec::new();
    let mut pos = size;
    let mut line_end = size;
    let mut last_chunk_len = 0usize;
    while pos > floor && recent.updated.is_none() {
        let start = pos.saturating_sub(TAIL_WINDOW).max(floor);
        let len = usize::try_from(pos - start)?;
        crate::storage::source_io::at(path, file.seek(SeekFrom::Start(start)))?;
        crate::storage::source_io::at(path, file.read_exact(&mut buf[..len]))?;
        last_chunk_len = len;
        let chunk_end = pos;
        let mut scan_end = len;
        while let Some(nl) = buf[..scan_end].iter().rposition(|&b| b == b'\n') {
            let line_start = start + nl as u64 + 1;
            if line_start < line_end {
                let done = if line_end <= chunk_end {
                    let end_in_buf = usize::try_from(line_end - start)?;
                    visit_recent_line(
                        &buf[(nl + 1)..end_in_buf],
                        &mut recent,
                        &mut last,
                    )
                } else {
                    let line_len = usize::try_from(line_end - line_start)?;
                    scratch.resize(line_len, 0);
                    crate::storage::source_io::at(
                        path,
                        file.seek(SeekFrom::Start(line_start)),
                    )?;
                    crate::storage::source_io::at(
                        path,
                        file.read_exact(&mut scratch),
                    )?;
                    visit_recent_line(&scratch, &mut recent, &mut last)
                };
                if done {
                    return Ok((recent, last));
                }
            }
            line_end = start + nl as u64;
            scan_end = nl;
        }
        pos = start;
    }
    if floor == 0 && recent.updated.is_none() && line_end > 0 {
        if line_end <= last_chunk_len as u64 {
            visit_recent_line(
                &buf[..usize::try_from(line_end)?],
                &mut recent,
                &mut last,
            );
        } else {
            scratch.resize(usize::try_from(line_end)?, 0);
            crate::storage::source_io::at(path, file.seek(SeekFrom::Start(0)))?;
            crate::storage::source_io::at(path, file.read_exact(&mut scratch))?;
            visit_recent_line(&scratch, &mut recent, &mut last);
        }
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
            let mut has_title = false;
            rollout::lines(path, |_, line, _| {
                if !first && (has_title || scan.head.len() >= TITLE_RECORDS) {
                    if let Some(fast) = parse_fast_record(line) {
                        scan.activity.visit_fast(&fast)?;
                        return Ok(true);
                    }
                    if let Some(record) = jsonl::pruned(line, &RECORD) {
                        scan.activity.visit(&record)?;
                    }
                    return Ok(true);
                }
                let record = rollout::object(line);
                if std::mem::take(&mut first) {
                    scan.header.clone_from(&record);
                }
                if let Some(record) = record {
                    scan.activity.visit(&record)?;
                    if !has_title
                        && message_title(std::slice::from_ref(&record))
                            .is_some()
                    {
                        has_title = true;
                    }
                    if scan.head.len() < TITLE_RECORDS {
                        scan.head.push(record);
                    }
                }
                Ok(true)
            })?;
            return Ok(scan);
        }
        let mut file = crate::storage::source_io::open(path)?;
        let size = file.metadata()?.len();
        if size <= jsonl::FULL_SCAN_LIMIT {
            let mut bytes =
                Vec::with_capacity(usize::try_from(size).unwrap_or(0));
            crate::storage::source_io::at(path, file.read_to_end(&mut bytes))?;
            let mut header = None;
            let mut head = Vec::new();
            let mut activity = Activity::default();
            let mut first = true;
            let mut has_title = false;
            let mut parsed_count = 0usize;
            for line in bytes
                .split(|byte| *byte == b'\n')
                .filter(|line| line.iter().any(|b| !b.is_ascii_whitespace()))
            {
                if !first && (has_title || parsed_count >= TITLE_RECORDS) {
                    if let Some(fast) = parse_fast_record(line) {
                        activity.visit_fast(&fast)?;
                        parsed_count += 1;
                        continue;
                    }
                    if let Some(record) = jsonl::pruned(line, &RECORD) {
                        activity.visit(&record)?;
                        parsed_count += 1;
                    }
                    continue;
                }
                let record = rollout::object(line);
                if std::mem::take(&mut first) {
                    header.clone_from(&record);
                }
                if let Some(record) = record {
                    activity.visit(&record)?;
                    parsed_count += 1;
                    if !has_title
                        && message_title(std::slice::from_ref(&record))
                            .is_some()
                    {
                        has_title = true;
                    }
                    if head.len() < TITLE_RECORDS {
                        head.push(record);
                    }
                }
            }
            return Ok(Scan {
                header,
                head,
                activity,
                complete: true,
            });
        }
        let metadata =
            jsonl::metadata_large(path, &mut file, size, TITLE_RECORDS, false)?;
        let mut activity = Activity::default();
        for record in &metadata.records {
            activity.visit(record)?;
        }
        if !metadata.complete {
            let (recent, last) = recent(path, &mut file, size)?;
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
            |path| {
                path.file_name().and_then(|name| name.to_str()).is_some_and(
                    |name| {
                        let name = name.strip_suffix(".zst").unwrap_or(name);
                        let name = name.strip_suffix(".jsonl").unwrap_or(name);
                        name.ends_with(&suffix)
                    },
                )
            },
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
        serde_json::to_value(enrichment::json_payload(data).as_ref()).unwrap()
    }

    fn write_json_payload(
        &self,
        data: &SessionData,
        summary: Option<&str>,
        writer: &mut dyn std::io::Write,
    ) -> crate::Result<()> {
        use serde::Serialize;
        #[derive(Serialize)]
        struct WithSummary<'a> {
            #[serde(flatten)]
            payload: &'a SessionData,
            summary: &'a str,
        }
        let payload = enrichment::json_payload(data);
        let mut serializer = serde_json::Serializer::with_formatter(
            writer,
            crate::compat::json::Formatter::default(),
        );
        if let Some(summary) = summary {
            WithSummary {
                payload: payload.as_ref(),
                summary,
            }
            .serialize(&mut serializer)?;
        } else {
            payload.as_ref().serialize(&mut serializer)?;
        }
        Ok(())
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
