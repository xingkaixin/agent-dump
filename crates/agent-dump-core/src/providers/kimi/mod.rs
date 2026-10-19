pub(super) mod transcript;
pub(super) mod wire;

use crate::compat::value::text;
use crate::providers::contract::{Provider, RawExport, Window};
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::providers::title::normalize_title;
use crate::session::timestamp::Timestamp;
use crate::session::{
    Session, SessionData, Stats, epoch_seconds, parse_timestamp,
};
use md5::{Digest, Md5};
use serde_json::Value;
use std::collections::HashMap;
use std::io::BufRead;
use std::path::{Path, PathBuf};

pub struct Kimi {
    roots: SourceRoots,
    settings: Option<Settings>,
}

#[derive(Default)]
struct Settings {
    work_dirs: HashMap<String, String>,
    model: String,
}

impl Settings {
    fn load(data: &Path) -> Self {
        let mut settings = Self::default();
        if let Some(raw) = std::fs::read(data.join("kimi.json"))
            .ok()
            .and_then(|bytes| crate::compat::json::from_slice(&bytes).ok())
            && let Some(directories) = raw["work_dirs"].as_array()
        {
            for entry in directories {
                if let Some(path) = entry["path"].as_str() {
                    settings.work_dirs.insert(
                        format!(
                            "{:032x}",
                            u128::from_be_bytes(
                                Md5::digest(path.as_bytes()).into()
                            )
                        ),
                        path.into(),
                    );
                }
            }
        }
        if let Some(model) = std::fs::read_to_string(data.join("config.toml"))
            .ok()
            .and_then(|config| configured_model(&config))
        {
            settings.model = model;
        }
        settings
    }
}

fn configured_model(config: &str) -> Option<String> {
    let config = config.parse::<toml_edit::DocumentMut>().ok()?;
    let key = config.get("default_model")?.as_str()?;
    let model = config
        .get("models")
        .and_then(|models| models.get(key))
        .and_then(|table| table.get("model"))
        .and_then(toml_edit::Item::as_str);
    Some(model.unwrap_or(key).to_owned())
}

pub(super) fn timestamp(value: &Value) -> Option<Timestamp> {
    let milliseconds = match value {
        Value::Number(number) => number.as_f64()?,
        Value::String(text) => {
            let text = text.trim().replacen(' ', "T", 1);
            match text.parse::<f64>() {
                Ok(number) => number,
                Err(_) => return parse_timestamp(&text),
            }
        }
        _ => return None,
    };
    epoch_seconds(milliseconds / 1000.0)
}

fn modified(path: &Path) -> Option<Timestamp> {
    Timestamp::try_from(path.metadata().ok()?.modified().ok()?).ok()
}

pub(super) fn title(text: &str) -> Option<String> {
    crate::providers::text::clean(text)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(normalize_title)
}

fn first_user_title(context: &Path, wire: &Path) -> Option<String> {
    for (path, is_wire) in [(context, false), (wire, true)] {
        let Ok(file) = crate::storage::source_io::open(path) else {
            continue;
        };
        for line in std::io::BufReader::new(file).split(b'\n') {
            let Ok(line) = line else {
                break;
            };
            let Ok(record) = crate::compat::json::from_slice(&line) else {
                continue;
            };
            let content = if is_wire {
                let message = &record["message"];
                if message["type"] != "TurnBegin" {
                    continue;
                }
                &message["payload"]["user_input"]
            } else if record["role"] == "user" {
                &record["content"]
            } else {
                continue;
            };
            if let Some(title) = title(&transcript::content_text(content)) {
                return Some(title);
            }
        }
    }
    None
}

fn subagent_wires(session: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(session.join("subagents")) else {
        return Vec::new();
    };
    let mut wires: Vec<_> = entries
        .flatten()
        .map(|entry| entry.path().join("wire.jsonl"))
        .filter(|path| path.is_file())
        .collect();
    wires.sort();
    wires
}

impl Kimi {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; \
                  source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                || file_sessions::environment_root("KIMI_SHARE_DIR", ".kimi"),
                "sessions",
                "data/kimi",
                "KIMI_SHARE_DIR/sessions",
            ),
            settings: None,
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(Some(3), |path, base| {
            let session = path.parent().unwrap_or(path);
            path.strip_prefix(base)
                .is_ok_and(|path| path.components().count() == 3)
                && path.file_name().is_some_and(|name| {
                    name == "state.json"
                        || (name == "metadata.json"
                            && !session.join("state.json").is_file())
                })
        })
    }

    fn settings(&mut self) -> &Settings {
        self.settings.get_or_insert_with(|| {
            self.roots
                .base
                .as_deref()
                .map_or_else(Settings::default, |base| {
                    Settings::load(base.parent().unwrap_or(base))
                })
        })
    }

    fn scan(path: &Path) -> crate::Result<Value> {
        crate::compat::json::from_slice(&crate::storage::source_io::read(path)?)
    }

    fn parse(
        &mut self,
        path: &Path,
        metadata: &Value,
        cutoff: Option<Timestamp>,
    ) -> crate::Result<Option<Session>> {
        if !metadata.is_object() {
            return Err("session metadata must be a JSON object".into());
        }
        let directory = path.parent().ok_or("Kimi session has no directory")?;
        let created_at = if let Some(created_at) =
            timestamp(&metadata["createdAt"])
                .or_else(|| timestamp(&metadata["created_at"]))
        {
            created_at
        } else {
            let source = directory.metadata()?;
            Timestamp::try_from(
                source.created().or_else(|_| source.modified())?,
            )?
        };
        if cutoff.is_some_and(|cutoff| created_at < cutoff) {
            return Ok(None);
        }
        let context = directory.join("context.jsonl");
        let wire = directory.join("wire.jsonl");
        if !context.exists() && !wire.exists() {
            return Ok(None);
        }
        let id = match text(&metadata["session_id"]).trim() {
            "" => directory
                .file_name()
                .unwrap_or_default()
                .to_string_lossy()
                .trim()
                .to_owned(),
            id => id.to_owned(),
        };
        if id.is_empty() {
            return Ok(None);
        }
        let updated_at = [
            metadata["wire_mtime"].as_f64().and_then(epoch_seconds),
            modified(&context),
            modified(&wire),
        ]
        .into_iter()
        .flatten()
        .fold(created_at, Timestamp::max);
        let explicit = if path.ends_with("state.json") {
            "custom_title"
        } else {
            "title"
        };
        let title = title(text(&metadata[explicit]))
            .or_else(|| first_user_title(&context, &wire))
            .unwrap_or_else(|| "Untitled Session".into());
        let hash = directory
            .parent()
            .and_then(Path::file_name)
            .unwrap_or_default()
            .to_string_lossy();
        let settings = self.settings();
        let cwd = settings.work_dirs.get(hash.as_ref()).cloned();
        let model = settings.model.clone();
        let message_count = if context.exists()
            && context.metadata()?.len()
                <= crate::providers::jsonl::FULL_SCAN_LIMIT
        {
            crate::providers::kimi::transcript::read(&context, &mut |_| Ok(()))
                .ok()
                .map(|messages| messages.len())
        } else {
            None
        };
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at,
            subtargets: Vec::new(),
            source_metadata: serde_json::json!({
                "context_file": context.exists().then_some(&context),
                "wire_file": wire.exists().then_some(&wire),
            }),
            source_path: directory.to_owned(),
            directory: cwd.unwrap_or_default(),
            version: Value::Null,
            model,
            project: None,
            message_count,
        }))
    }
}

impl Provider for Kimi {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.settings = None;
        file_sessions::discover(
            self.files()?,
            window,
            false,
            Self::scan,
            |path, metadata, cutoff| self.parse(path, &metadata, cutoff),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        self.settings = None;
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.clone().as_deref(),
            files,
            id,
            |path| {
                path.parent()
                    .and_then(Path::file_name)
                    .is_some_and(|name| name == id)
            },
            |path| self.parse(path, &Self::scan(path)?, None),
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        let context = session.source_path.join("context.jsonl");
        let wire = session.source_path.join("wire.jsonl");
        let mut messages = if context.exists() {
            crate::providers::kimi::transcript::read(&context, diagnostics)?
        } else {
            if !wire.exists() {
                return Err(crate::providers::error::ProviderError::missing(
                    ["wire.jsonl is missing for this Kimi session"; 2],
                    &wire,
                    Vec::new(),
                    vec![
                        crate::storage::source_io::path_text(&context),
                        crate::storage::source_io::path_text(&wire),
                    ],
                    vec![
                        [
                            "Confirm `wire.jsonl` in the session directory \
                             has not been cleaned up.",
                            "确认会话目录中的 `wire.jsonl` 未被清理。",
                        ],
                        [
                            "If only `context.jsonl` exists, use the context \
                             export path.",
                            "如果只有 `context.jsonl`，请改走 context 导出路径。",
                        ],
                    ],
                ).into());
            }
            crate::providers::kimi::wire::read(
                &wire,
                (!session.model.is_empty()).then_some(session.model.as_str()),
                diagnostics,
            )?
        };
        crate::providers::text::clean_messages(&mut messages);
        let mut stats = Stats {
            message_count: messages.len(),
            total_tokens: Some(0.into()),
            ..Stats::default()
        };
        let wires = wire
            .exists()
            .then(|| wire.clone())
            .into_iter()
            .chain(subagent_wires(&session.source_path));
        for path in wires {
            crate::providers::jsonl::scan(&path, diagnostics, |record, _| {
                match crate::providers::kimi::wire::usage(&record) {
                    Some(usage) => stats
                        .add_tokens(&usage.input.into(), &usage.output.into()),
                    None => Ok(()),
                }
            })?;
        }
        let raw = if context.exists() { &context } else { &wire };
        crate::providers::jsonl::scan(raw, diagnostics, |record, _| {
            if record["role"] == "_usage" && record["token_count"].is_number() {
                stats.total_tokens =
                    Some(crate::compat::value::integer_number(
                        &record["token_count"],
                    ));
            }
            Ok(())
        })?;
        Ok(session.payload(messages, stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        ["context.jsonl", "wire.jsonl"]
            .into_iter()
            .map(|name| session.source_path.join(name))
            .filter(|path| path.exists())
            .collect()
    }

    fn source_root(&self) -> &Path {
        self.roots.owned()
    }

    fn select_source(&mut self) -> crate::Result<Option<&Path>> {
        self.roots.select()
    }

    fn raw_export(&self, session: &Session) -> crate::Result<RawExport> {
        let roots = ["context.jsonl", "wire.jsonl"]
            .map(|name| {
                crate::storage::source_io::path_text(
                    &session.source_path.join(name),
                )
            })
            .to_vec();
        let source = ["context_file", "wire_file"]
            .into_iter()
            .find_map(|key| {
                session.source_metadata[key]
                    .as_str()
                    .filter(|path| !path.is_empty())
            })
            .map(PathBuf::from);
        let Some(source) = source else {
            return Err(crate::providers::error::ProviderError::missing(
                ["no raw session file is available for this Kimi session"; 2],
                &session.source_path,
                Vec::new(),
                roots,
                vec![
                    [
                        "Confirm the session directory holds at least \
                         `context.jsonl` or `wire.jsonl`.",
                        "确认该会话目录下至少存在 `context.jsonl` 或 \
                         `wire.jsonl`。",
                    ],
                    [
                        "For a readable export, use `--format json` or \
                         `--format markdown`.",
                        "若只需要可读导出，改用 `--format json` 或 \
                         `--format markdown`。",
                    ],
                ],
            )
            .into());
        };
        if !source.exists() {
            return Err(crate::providers::error::ProviderError::missing(
                ["raw session file is missing"; 2],
                &source,
                Vec::new(),
                roots,
                vec![
                    [
                        "Confirm the original Kimi session file has not been moved or cleaned up.",
                        "确认原始 Kimi 会话文件没有被移动或清理。",
                    ],
                    [
                        "Re-run `agent-dump --list` to check whether the session is still visible.",
                        "重新运行 `agent-dump --list` 检查该会话是否仍可见。",
                    ],
                ],
            )
            .into());
        }
        Ok(RawExport::File(source))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::providers::source_tests::source_selection(
            "sessions",
            false,
            |roots| Kimi {
                roots,
                settings: None,
            },
            |base| {
                let path = base.join("project/kept");
                std::fs::create_dir_all(&path).unwrap();
                std::fs::write(
                    path.join("metadata.json"),
                    r#"{"session_id":"kept","title":"Kept","wire_mtime":1768478400}"#,
                )
                .unwrap();
                std::fs::write(
                    path.join("context.jsonl"),
                    concat!(r#"{"role":"user","content":"Keep"}"#, "\n"),
                )
                .unwrap();
                path
            },
        );
    }
    use crate::providers::source_tests::assert_missing;

    fn fixture(root: &Path, context: bool) -> (Kimi, Session) {
        let directory = root.join("sessions/project/kept");
        std::fs::create_dir_all(&directory).unwrap();
        std::fs::write(
            directory.join("metadata.json"),
            r#"{"session_id":"kept","title":"Kept","wire_mtime":1768478400}"#,
        )
        .unwrap();
        if context {
            std::fs::write(
                directory.join("context.jsonl"),
                "{\"role\":\"user\",\"content\":\"Context\"}\n",
            )
            .unwrap();
        }
        std::fs::write(
            directory.join("wire.jsonl"),
            "{\"timestamp\":1768478400,\"message\":{\"type\":\"TurnBegin\",\
             \"payload\":{\"user_input\":[{\"text\":\"Wire\"}]}}}\n",
        )
        .unwrap();
        let mut provider = Kimi {
            roots: SourceRoots::fixed(
                root.into(),
                "sessions",
                "data/kimi",
                "KIMI_SHARE_DIR/sessions",
            ),
            settings: None,
        };
        let session = provider
            .find("kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        (provider, session)
    }

    fn roots(session: &Session) -> Vec<String> {
        ["context.jsonl", "wire.jsonl"]
            .map(|name| {
                crate::storage::source_io::path_text(
                    &session.source_path.join(name),
                )
            })
            .to_vec()
    }

    fn text(provider: &Kimi, session: &Session) -> String {
        let data = serde_json::to_value(
            provider.read(session, false, &mut |_| Ok(())).unwrap(),
        )
        .unwrap();
        data["messages"][0]["parts"][0]["text"]
            .as_str()
            .unwrap()
            .to_owned()
    }

    #[test]
    fn context_removed_keeps_raw_identity_while_body_can_use_wire() {
        let directory = tempfile::tempdir().unwrap();
        let (mut provider, session) = fixture(directory.path(), true);
        let context = session.source_path.join("context.jsonl");
        assert_eq!(text(&provider, &session), "Context");
        std::fs::remove_file(&context).unwrap();
        assert_eq!(text(&provider, &session), "Wire");
        let error = provider.raw_export(&session).err().unwrap();
        assert_missing(
            error.as_ref(),
            "raw session file is missing",
            &context,
            &roots(&session),
            "original Kimi session",
        );
        let current = provider
            .find("kept", &mut |_| Ok(()))
            .unwrap()
            .session
            .unwrap();
        assert!(matches!(
            provider.raw_export(&current).unwrap(),
            RawExport::File(path)
                if path == session.source_path.join("wire.jsonl")
        ));
        assert!(!context.exists());
    }

    #[test]
    fn new_context_does_not_replace_snapshot_raw_wire() {
        let directory = tempfile::tempdir().unwrap();
        let (provider, session) = fixture(directory.path(), false);
        let wire = session.source_path.join("wire.jsonl");
        let before = std::fs::read(&wire).unwrap();
        std::fs::write(
            session.source_path.join("context.jsonl"),
            "{\"role\":\"user\",\"content\":\"New context\"}\n",
        )
        .unwrap();
        assert_eq!(text(&provider, &session), "New context");
        assert!(
            matches!(provider.raw_export(&session).unwrap(), RawExport::File(path) if path == wire)
        );
        assert_eq!(std::fs::read(wire).unwrap(), before);
    }

    #[test]
    fn missing_body_and_raw_keep_distinct_evidence() {
        let directory = tempfile::tempdir().unwrap();
        let (provider, session) = fixture(directory.path(), true);
        let context = session.source_path.join("context.jsonl");
        let wire = session.source_path.join("wire.jsonl");
        std::fs::remove_file(&context).unwrap();
        std::fs::remove_file(&wire).unwrap();
        let error = provider
            .read(&session, false, &mut |_| Ok(()))
            .err()
            .unwrap();
        assert_missing(
            error.as_ref(),
            "wire.jsonl is missing for this Kimi session",
            &wire,
            &roots(&session),
            "wire.jsonl",
        );
        let error = provider.raw_export(&session).err().unwrap();
        assert_missing(
            error.as_ref(),
            "raw session file is missing",
            &context,
            &roots(&session),
            "original Kimi session",
        );
        assert!(!context.exists() && !wire.exists());
    }

    #[test]
    fn raw_without_snapshot_file_evidence_does_not_guess_a_source() {
        let directory = tempfile::tempdir().unwrap();
        let (provider, mut session) = fixture(directory.path(), true);
        session.source_metadata = Value::Null;
        let error = provider.raw_export(&session).err().unwrap();
        assert_missing(
            error.as_ref(),
            "no raw session file is available for this Kimi session",
            &session.source_path,
            &roots(&session),
            "at least",
        );
    }
}
