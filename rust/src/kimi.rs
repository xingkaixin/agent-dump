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
            roots: SourceRoots::resolve(root, "sessions", "data/kimi", "KIMI_SHARE_DIR/sessions"),
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
            source_metadata: serde_json::json!({
                "context_file": context.exists().then_some(&context),
                "wire_file": directory.join("wire.jsonl").exists().then(|| directory.join("wire.jsonl")),
            }),
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
    fn discover(&mut self, days: i64) -> crate::Result<crate::provider::Discovery> {
        self.work_dirs = None;
        file_sessions::discover(&self.files()?, days, false, |path, cutoff| {
            self.parse(path, Some(cutoff))
        })
    }

    fn find(&mut self, id: &str) -> crate::Result<crate::provider::Lookup> {
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
            if !wire.exists() {
                return Err(crate::provider_error::ProviderError::missing(
                    ["wire.jsonl is missing for this Kimi session"; 2],
                    &wire,
                    Vec::new(),
                    vec![context.display().to_string(), wire.display().to_string()],
                    vec![
                        ["Confirm `wire.jsonl` in the session directory has not been cleaned up.", "确认会话目录中的 `wire.jsonl` 未被清理。"],
                        ["If only `context.jsonl` exists, use the context export path.", "如果只有 `context.jsonl`，请改走 context 导出路径。"],
                    ],
                ).into());
            }
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

    fn search_roots(&self) -> Vec<(&'static str, PathBuf)> {
        self.roots.search_roots()
    }

    fn source_root(&self) -> &Path {
        &self.roots.owned
    }

    fn raw_export(&self, session: &Session) -> crate::Result<RawExport> {
        let roots = ["context.jsonl", "wire.jsonl"]
            .map(|name| session.source_path.join(name).display().to_string())
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
            return Err(crate::provider_error::ProviderError::missing(
                ["no raw session file is available for this Kimi session"; 2],
                &session.source_path,
                Vec::new(),
                roots,
                vec![
                    ["Confirm the session directory holds at least `context.jsonl` or `wire.jsonl`.", "确认该会话目录下至少存在 `context.jsonl` 或 `wire.jsonl`。"],
                    ["For a readable export, use `--format json` or `--format markdown`.", "若只需要可读导出，改用 `--format json` 或 `--format markdown`。"],
                ],
            ).into());
        };
        if !source.exists() {
            return Err(crate::provider_error::ProviderError::missing(
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
    use crate::source_tests::assert_missing;

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
        std::fs::write(directory.join("wire.jsonl"), "{\"timestamp\":1768478400,\"message\":{\"type\":\"TurnBegin\",\"payload\":{\"user_input\":[{\"text\":\"Wire\"}]}}}\n").unwrap();
        let mut provider = Kimi {
            roots: SourceRoots::resolve(
                root.into(),
                "sessions",
                "data/kimi",
                "KIMI_SHARE_DIR/sessions",
            ),
            work_dirs: None,
        };
        let session = provider.find("kept").unwrap().session.unwrap();
        (provider, session)
    }

    fn roots(session: &Session) -> Vec<String> {
        ["context.jsonl", "wire.jsonl"]
            .map(|name| session.source_path.join(name).display().to_string())
            .to_vec()
    }

    fn text(provider: &Kimi, session: &Session) -> String {
        let data = serde_json::to_value(provider.read(session, false).unwrap()).unwrap();
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
        let current = provider.find("kept").unwrap().session.unwrap();
        assert!(
            matches!(provider.raw_export(&current).unwrap(), RawExport::File(path) if path == session.source_path.join("wire.jsonl"))
        );
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
        let error = provider.read(&session, false).err().unwrap();
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
