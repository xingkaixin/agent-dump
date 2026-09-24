use crate::file_sessions::{self, SourceRoots};
use crate::provider::{Provider, RawExport};
use crate::session::{Session, SessionData, Stats, epoch_seconds};
use crate::title::{basename, normalize_title};
use crate::value::{integer, text};
use jiff::Timestamp;
use md5::{Digest, Md5};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Kimi {
    roots: SourceRoots,
    work_dirs: Option<HashMap<String, String>>,
}

impl Kimi {
    pub fn open() -> crate::Result<Self> {
        let root = file_sessions::environment_root("KIMI_SHARE_DIR", ".kimi")?;
        Ok(Self {
            roots: SourceRoots::resolve(root, "sessions", "data/kimi"),
            work_dirs: None,
        })
    }

    fn files(&self) -> crate::Result<Vec<PathBuf>> {
        self.roots.files(None, |path| {
            path.file_name().is_some_and(|name| name == "metadata.json")
        })
    }

    fn working_directory(&mut self, hash: &str) -> String {
        let mapping = self.work_dirs.get_or_insert_with(|| {
            let mut mapping = HashMap::new();
            let path = self
                .roots
                .base
                .parent()
                .unwrap_or(&self.roots.base)
                .join("kimi.json");
            if let Some(raw) = std::fs::read(path)
                .ok()
                .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
                && let Some(directories) = raw["work_dirs"].as_array()
            {
                for entry in directories {
                    if let Some(path) = entry["path"].as_str() {
                        mapping.insert(format!("{:x}", Md5::digest(path.as_bytes())), path.into());
                    }
                }
            }
            mapping
        });
        mapping.get(hash).cloned().unwrap_or_default()
    }

    fn parse(&mut self, path: &Path, cutoff: Option<Timestamp>) -> crate::Result<Option<Session>> {
        let metadata: Value = serde_json::from_slice(&std::fs::read(path)?)?;
        if !metadata.is_object() {
            return Err("Kimi session metadata must be a JSON object".into());
        }
        let created_at = metadata["wire_mtime"]
            .as_f64()
            .and_then(epoch_seconds)
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        if cutoff.is_some_and(|cutoff| created_at < cutoff) {
            return Ok(None);
        }
        let directory = path.parent().ok_or("Kimi session has no directory")?;
        let context = directory.join("context.jsonl");
        if !context.exists() && !directory.join("wire.jsonl").exists() {
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
        let hash = directory
            .parent()
            .and_then(Path::file_name)
            .unwrap_or_default()
            .to_string_lossy();
        let cwd = self.working_directory(&hash);
        let title = normalize_title(text(&metadata["title"]))
            .or_else(|| basename(&cwd))
            .unwrap_or_else(|| "Untitled Session".into());
        let message_count =
            if context.exists() && context.metadata()?.len() <= crate::jsonl::FULL_SCAN_LIMIT {
                crate::kimi_transcript::read(&context, false)
                    .ok()
                    .map(|messages| messages.len())
            } else {
                None
            };
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at: created_at,
            subtargets: Vec::new(),
            source_metadata: serde_json::Value::Null,
            source_path: directory.to_owned(),
            directory: cwd,
            version: Value::Null,
            model: String::new(),
            project: None,
            message_count,
        }))
    }
}

impl Provider for Kimi {
    fn discover(&mut self, days: i64) -> crate::Result<Vec<Session>> {
        self.work_dirs = None;
        file_sessions::discover(&self.files()?, days, false, |path, cutoff| {
            self.parse(path, Some(cutoff))
        })
    }

    fn find(&mut self, id: &str) -> crate::Result<Session> {
        self.work_dirs = None;
        file_sessions::find(
            &self.roots.base.clone(),
            &self.files()?,
            id,
            |path| {
                path.parent()
                    .and_then(Path::file_name)
                    .is_some_and(|name| name == id)
            },
            |path| self.parse(path, None),
        )
    }

    fn read(&self, session: &Session, _zh: bool) -> crate::Result<SessionData> {
        let context = session.source_path.join("context.jsonl");
        let wire = session.source_path.join("wire.jsonl");
        let messages = if context.exists() {
            crate::kimi_transcript::read(&context, true)?
        } else {
            crate::kimi_wire::read(&wire)?
        };
        let mut stats = Stats {
            message_count: messages.len(),
            total_tokens: Some(0),
            ..Stats::default()
        };
        if wire.exists() {
            crate::jsonl::scan(&wire, |record| {
                let usage = &record["message"]["usage"];
                stats.add_tokens(&usage["input_tokens"], &usage["output_tokens"])
            })?;
        }
        let raw = if context.exists() { &context } else { &wire };
        crate::jsonl::scan(raw, |record| {
            if record["role"] == "_usage" && record["token_count"].is_number() {
                stats.total_tokens = Some(integer(&record["token_count"]));
            }
            Ok(())
        })?;
        Ok(session.payload(messages, stats))
    }

    fn source_root(&self) -> &Path {
        &self.roots.owned
    }

    fn raw_export(&self, session: &Session) -> RawExport {
        let context = session.source_path.join("context.jsonl");
        RawExport::File(if context.exists() {
            context
        } else {
            session.source_path.join("wire.jsonl")
        })
    }
}
