use crate::providers::claude::title_line;
use crate::providers::claude::transcript::Decoder;
use crate::providers::contract::{
    DiagnosticSink, Provider, Window, source_roots,
};
use crate::providers::error::ProviderError;
use crate::providers::files::{
    self as file_sessions, SourceFiles, SourceRoots,
};
use crate::providers::title::basename;
use crate::session::timestamp::Timestamp;
use crate::session::{Message, Part, Session, SessionData, Stats};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub struct Droid {
    roots: SourceRoots,
    models: Option<HashMap<String, String>>,
}

struct Transcript {
    start: Option<Value>,
    messages: Vec<Message>,
}

struct Scan {
    start: Value,
    created: i64,
    updated: i64,
    message_count: usize,
    prompt: Option<String>,
    model: Option<String>,
}

fn json_file(path: &Path) -> Value {
    crate::storage::source_io::read(path)
        .ok()
        .and_then(|bytes| crate::compat::json::from_slice(&bytes).ok())
        .unwrap_or_default()
}

fn settings(path: &Path) -> Value {
    json_file(&path.with_extension("settings.json"))
}

fn custom_models(root: &Path) -> HashMap<String, String> {
    json_file(&root.join("settings.json"))["customModels"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|entry| {
            Some((
                entry["id"].as_str()?.to_owned(),
                entry["model"].as_str()?.to_owned(),
            ))
        })
        .collect()
}

/// Droid stores whole Anthropic messages, so each record is decoded as one
/// Claude Code record that starts a new message.
fn transcript(
    path: &Path,
    diagnostics: &mut DiagnosticSink<'_>,
) -> crate::Result<Transcript> {
    let mut start = None;
    let mut decoder = Decoder::new("droid", HashMap::new());
    crate::providers::jsonl::scan_numbered(
        path,
        diagnostics,
        |number, mut record, diagnostics| {
            if number == 1 && record["type"] == "session_start" {
                start = Some(record);
                return Ok(());
            }
            let message = &record["message"];
            if record["type"] != "message"
                || !message.is_object()
                || message["visibility"] == "llm_only"
            {
                return Ok(());
            }
            let role = if message["role"] == "assistant" {
                "assistant"
            } else {
                "user"
            };
            let content =
                match record.pointer_mut("/message/content").map(Value::take) {
                    Some(Value::String(text)) => {
                        json!([{"type": "text", "text": text}])
                    }
                    content => content.unwrap_or_default(),
                };
            decoder.reset();
            decoder.convert(
                &json!({
                    "type": role,
                    "uuid": record["id"],
                    "timestamp": record["timestamp"],
                    "message": {"content": content},
                }),
                diagnostics,
            )
        },
    )?;
    Ok(Transcript {
        start,
        messages: decoder.finish(),
    })
}

fn timestamp(milliseconds: i64) -> crate::Result<Timestamp> {
    Timestamp::from_microsecond(milliseconds.saturating_mul(1000))
}

impl Droid {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::new(
                || {
                    let home = file_sessions::environment_path(
                        "FACTORY_HOME_OVERRIDE",
                    )?;
                    Ok(home
                        .map_or_else(file_sessions::home, Ok)?
                        .join(".factory"))
                },
                "sessions",
                "data/droid",
                "FACTORY_HOME_OVERRIDE/.factory/sessions",
            ),
            models: None,
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(Some(2), |path, _| {
            path.extension().is_some_and(|ext| ext == "jsonl")
        })
    }

    fn scan(path: &Path) -> crate::Result<Option<Scan>> {
        let Transcript { start, messages } = transcript(path, &mut |_| Ok(()))?;
        let (Some(start), Some(first), Some(last)) =
            (start, messages.first(), messages.last())
        else {
            return Ok(None);
        };
        let prompt = messages
            .iter()
            .filter(|message| message.role == "user")
            .flat_map(|message| &message.parts)
            .find_map(|part| match part {
                Part::Text(part) => title_line(&part.text),
                _ => None,
            });
        let model = settings(path)["model"]
            .as_str()
            .map(str::trim)
            .filter(|model| !model.is_empty())
            .map(str::to_owned);
        Ok(Some(Scan {
            start,
            created: first.time_created,
            updated: last.time_created,
            message_count: messages.len(),
            prompt,
            model,
        }))
    }

    fn model(&mut self, id: &str) -> String {
        let models = self
            .models
            .get_or_insert_with(|| custom_models(self.roots.owned()));
        models.get(id).cloned().unwrap_or_else(|| {
            id.strip_prefix("custom:").unwrap_or(id).to_owned()
        })
    }

    fn parse(
        &mut self,
        path: &Path,
        scan: Option<Scan>,
    ) -> crate::Result<Option<Session>> {
        let Some(scan) = scan else {
            return Ok(None);
        };
        let field = |keys: &[&str]| {
            keys.iter()
                .filter_map(|key| scan.start[*key].as_str().map(str::trim))
                .find(|value| !value.is_empty())
        };
        let directory = field(&["lastCwd", "cwd"]).unwrap_or_default();
        let title = field(&["sessionTitle", "title"])
            .filter(|title| *title != "New Session")
            .and_then(title_line)
            .or(scan.prompt)
            .or_else(|| basename(directory))
            .unwrap_or_else(|| "Untitled Session".into());
        let created_at = timestamp(scan.created)?;
        let id = path
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        Ok(Some(Session {
            directory: directory.to_owned(),
            model: scan
                .model
                .map(|model| self.model(&model))
                .unwrap_or_default(),
            message_count: Some(scan.message_count),
            ..Session::new(
                id,
                title,
                path.to_owned(),
                created_at,
                timestamp(scan.updated)?.max(created_at),
            )
        }))
    }
}

impl Provider for Droid {
    fn discover(
        &mut self,
        window: Window,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        self.models = None;
        file_sessions::discover(
            self.files()?,
            window,
            true,
            Self::scan,
            |path, scan, _| self.parse(path, scan),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        self.models = None;
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.clone().as_deref(),
            files,
            id,
            |path| path.file_stem().is_some_and(|name| name == id),
            |path| self.parse(path, Self::scan(path)?),
        )
    }

    fn read(
        &self,
        session: &Session,
        _zh: bool,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionData> {
        if !session.source_path.exists() {
            return Err(ProviderError::missing(
                ["session source file is missing"; 2],
                &session.source_path,
                Vec::new(),
                source_roots(self)?,
                vec![
                    ["Confirm the Droid session file is still under the sessions directory.", "确认 Droid 会话文件仍位于 sessions 目录下。"],
                    ["Re-run `agent-dump --list` to confirm the session still exists.", "重新运行 `agent-dump --list` 确认该会话是否仍存在。"],
                ],
            ).into());
        }
        let messages = transcript(&session.source_path, diagnostics)?.messages;
        let settings = settings(&session.source_path);
        let usage =
            |key: &str| settings["tokenUsage"][key].as_u64().unwrap_or(0);
        let stats = Stats {
            message_count: messages.len(),
            total_input_tokens: [
                "inputTokens",
                "cacheReadTokens",
                "cacheCreationTokens",
            ]
            .into_iter()
            .map(usage)
            .fold(0, u64::saturating_add)
            .into(),
            total_output_tokens: usage("outputTokens").into(),
            ..Stats::default()
        };
        Ok(session.payload(messages, stats))
    }

    fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
        self.roots.search_roots()
    }

    fn change_sources(&self, session: &Session) -> Vec<PathBuf> {
        vec![
            session.source_path.clone(),
            session.source_path.with_extension("settings.json"),
        ]
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
            "sessions",
            false,
            |roots| Droid {
                roots,
                models: None,
            },
            |base| {
                let path = base.join("kept.jsonl");
                std::fs::create_dir_all(base).unwrap();
                std::fs::write(&path, concat!(r#"{"type":"session_start","id":"kept"}"#, "\n", r#"{"type":"message","id":"m","timestamp":"2026-01-15T00:00:00Z","message":{"role":"user","content":"Keep"}}"#, "\n")).unwrap();
                path
            },
        );
    }
}
