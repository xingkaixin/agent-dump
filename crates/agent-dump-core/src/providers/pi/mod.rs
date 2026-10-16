pub(super) mod transcript;

use crate::compat::value::{field, text, truthy};
use crate::providers::contract::Provider;
use crate::providers::files::{
    self as file_sessions, Located, SourceFiles, SourceRoots,
};
use crate::providers::title::{basename, normalize_title};
use crate::session::timestamp::Timestamp;
use crate::session::{Session, SessionData, epoch_seconds, parse_timestamp};
use serde_json::Value;
use std::path::{Path, PathBuf};

pub struct Pi {
    roots: SourceRoots,
}

fn session_directory() -> crate::Result<Located> {
    let independent = |sessions: PathBuf, label| Located {
        owner: sessions.clone(),
        sessions,
        label,
    };
    if let Some(sessions) =
        file_sessions::environment_path("PI_CODING_AGENT_SESSION_DIR")?
    {
        return Ok(independent(sessions, "PI_CODING_AGENT_SESSION_DIR"));
    }
    let (owner, agent, label) = if let Some(agent) =
        file_sessions::environment_path("PI_CODING_AGENT_DIR")?
    {
        (agent.clone(), agent, "PI_CODING_AGENT_DIR/sessions")
    } else {
        let home = file_sessions::environment_root("PI_HOME", ".pi")?;
        (home.clone(), home.join("agent"), "PI_HOME/agent/sessions")
    };
    if let Some(sessions) = settings_session_directory(&agent)? {
        return Ok(independent(sessions, "Pi settings.json sessionDir"));
    }
    Ok(Located {
        owner,
        sessions: agent.join("sessions"),
        label,
    })
}

fn settings_session_directory(agent: &Path) -> crate::Result<Option<PathBuf>> {
    let Ok(bytes) =
        crate::storage::source_io::read(&agent.join("settings.json"))
    else {
        return Ok(None);
    };
    let Ok(settings) = crate::compat::json::from_slice(&bytes) else {
        return Ok(None);
    };
    let Some(directory) = settings["sessionDir"]
        .as_str()
        .map(str::trim)
        .filter(|directory| !directory.is_empty())
    else {
        return Ok(None);
    };
    // Pi resolves a relative sessionDir from its own working directory.
    let directory = file_sessions::expand_home(directory)?;
    Ok(directory.is_absolute().then_some(directory))
}

impl Pi {
    #[allow(
        clippy::unnecessary_wraps,
        reason = "Provider factories share the fallible registry interface; source access is deferred"
    )]
    pub fn open() -> crate::Result<Self> {
        Ok(Self {
            roots: SourceRoots::located(session_directory, "data/pi"),
        })
    }

    fn files(&mut self) -> crate::Result<SourceFiles> {
        self.roots.files(None, |path, _| {
            path.extension().is_some_and(|ext| ext == "jsonl")
        })
    }

    fn scan(path: &Path) -> crate::Result<crate::providers::jsonl::Metadata> {
        crate::providers::jsonl::metadata(path, 20, None)
    }

    fn parse(
        path: &Path,
        scan: crate::providers::jsonl::Metadata,
    ) -> crate::Result<Option<Session>> {
        let Some(header) =
            scan.header.filter(|header| header["type"] == "session")
        else {
            return Ok(None);
        };
        let id = if truthy(&header["id"]) {
            field(&header, "id").trim().to_owned()
        } else {
            path.file_stem()
                .unwrap_or_default()
                .to_string_lossy()
                .trim()
                .to_owned()
        };
        if id.is_empty() {
            return Ok(None);
        }
        let created_at = datetime(&header["timestamp"])
            .unwrap_or(Timestamp::try_from(path.metadata()?.modified()?)?);
        let mut updated_at = created_at;
        let mut message_count = 0;
        let mut model = String::new();
        let mut title = None;
        for record in scan.records.iter().chain(scan.tail.iter()) {
            if let Some(timestamp) = datetime(&record["timestamp"]) {
                updated_at = updated_at.max(timestamp);
            }
            if record["type"] == "message" {
                message_count += 1;
                if model.is_empty() {
                    text(&record["message"]["model"])
                        .trim()
                        .clone_into(&mut model);
                }
            }
            if let Some(name) = session_name(record) {
                title = Some(name);
            }
        }
        let title = title
            .or_else(|| {
                scan.records.iter().find_map(|record| {
                    (record["type"] == "message"
                        && record["message"]["role"] == "user")
                        .then(|| {
                            normalize_title(&content_text(
                                &record["message"]["content"],
                            ))
                        })
                        .flatten()
                })
            })
            .or_else(|| crate::providers::title::value_basename(&header["cwd"]))
            .or_else(|| {
                path.parent()
                    .and_then(|path| basename(&path.to_string_lossy()))
            })
            .unwrap_or_else(|| "Untitled Session".into());
        Ok(Some(Session {
            id,
            title,
            created_at,
            updated_at,
            subtargets: Vec::new(),
            source_metadata: serde_json::json!({"cwd": header.get("cwd").cloned().unwrap_or_else(|| "".into())}),
            source_path: path.to_owned(),
            directory: text(&header["cwd"]).into(),
            version: header["version"].clone(),
            model,
            project: None,
            message_count: scan.complete.then_some(message_count),
        }))
    }
}

impl Provider for Pi {
    fn discover(
        &mut self,
        days: Option<i64>,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Discovery> {
        file_sessions::discover(
            self.files()?,
            days,
            true,
            Self::scan,
            |path, scan, _| Self::parse(path, scan),
        )
    }

    fn find(
        &mut self,
        id: &str,
        _diagnostics: &mut crate::providers::contract::DiagnosticSink<'_>,
    ) -> crate::Result<crate::providers::contract::Lookup> {
        let suffix = format!("{id}.jsonl");
        let files = self.files()?;
        file_sessions::find(
            self.roots.base.as_deref(),
            files,
            id,
            |path| {
                path.file_name().is_some_and(|name| {
                    name.to_string_lossy().ends_with(&suffix)
                })
            },
            |path| Self::parse(path, Self::scan(path)?),
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
                    ["Confirm the Pi session file is still under the Pi session directory or the local development data directory.", "确认 Pi 会话文件仍在 Pi 会话目录或本地开发数据目录。"],
                    ["Re-run `agent-dump --list` to confirm the session id still exists.", "重新运行 `agent-dump --list` 确认会话 ID 是否仍存在。"],
                ],
            ).into());
        }
        crate::providers::pi::transcript::read(session, diagnostics)
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

pub fn datetime(value: &Value) -> Option<Timestamp> {
    if let Some(number) = value.as_f64() {
        return epoch_seconds(number / 1000.0);
    }
    parse_timestamp(value.as_str()?.trim())
}

pub fn session_name(record: &Value) -> Option<String> {
    (record["type"] == "session_info")
        .then(|| normalize_title(text(&record["name"])))
        .flatten()
}

#[derive(Default)]
pub struct Titles {
    named: Option<String>,
    slot: Option<String>,
    prompt: Option<String>,
}

impl Titles {
    pub fn add(&mut self, record: &Value) {
        match text(&record["type"]) {
            "session_info" => {
                if let Some(name) = title(text(&record["name"])) {
                    self.named = Some(name);
                }
            }
            "title" => self.slot = title(text(&record["title"])),
            "message"
                if self.prompt.is_none()
                    && record["message"]["role"] == "user" =>
            {
                self.prompt =
                    title(&prompt_text(&record["message"]["content"]));
            }
            _ => {}
        }
    }

    pub fn resolve(self, header: &Value) -> Option<String> {
        self.named
            .or(self.slot)
            .or_else(|| title(text(&header["title"])))
            .or(self.prompt)
    }
}

fn title(value: &str) -> Option<String> {
    crate::providers::text::clean(value)
        .lines()
        .find(|line| !line.trim().is_empty())
        .and_then(normalize_title)
}

fn prompt_text(content: &Value) -> String {
    match content {
        Value::String(prompt) => prompt.clone(),
        Value::Array(items) => items
            .iter()
            .filter(|item| item["type"] == "text")
            .map(|item| text(&item["text"]))
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

fn content_text(content: &Value) -> String {
    if let Some(text) = content.as_str() {
        return text.into();
    }
    let Some(items) = content.as_array() else {
        return String::new();
    };
    items
        .iter()
        .filter_map(|item| {
            if let Some(text) = item.as_str() {
                return Some(text.to_owned());
            }
            match text(&item["type"]) {
                "text" => Some(field(item, "text")),
                "thinking" => Some(field(item, "thinking")),
                _ => None,
            }
        })
        .filter(|text| !text.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn write(path: &Path, records: &[Value]) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let lines: Vec<_> = records.iter().map(Value::to_string).collect();
        std::fs::write(path, lines.join("\n")).unwrap();
    }

    #[test]
    fn export_keeps_only_the_active_branch() {
        let directory = tempfile::tempdir().unwrap();
        let sessions = directory.path().join("agent/sessions");
        write(
            &sessions.join("tree.jsonl"),
            &[
                json!({"type":"session","id":"tree","cwd":"/work/tree","timestamp":"2026-01-15T00:00:00Z"}),
                json!({"type":"message","id":"u","parentId":null,"message":{"role":"user","content":"Prompt"}}),
                json!({"type":"message","id":"old","parentId":"u","message":{"role":"assistant","content":"Abandoned","usage":{"input":1000}}}),
                json!({"type":"session_info","id":"old-name","parentId":"old","name":"Abandoned name"}),
                json!({"type":"message","id":"a","parentId":"u","message":{"role":"assistant","content":[{"type":"toolCall","id":"call","name":"read","arguments":{"path":"a"}}],"usage":{"input":100,"output":20,"cacheRead":10,"cacheWrite":5,"totalTokens":135,"cost":{"total":0.25}}}}),
                json!({"type":"message","id":"r","parentId":"a","message":{"role":"toolResult","toolCallId":"call","toolName":"read","content":[{"type":"text","text":"Result"}],"isError":false,"details":{"lines":1}}}),
                json!({"type":"custom_message","id":"hidden","parentId":"r","display":false,"content":"Hidden"}),
                json!({"type":"message","id":"note","parentId":"hidden","message":{"role":"custom","content":"Hidden note"}}),
                json!({"type":"custom_message","id":"shown","parentId":"note","display":true,"content":"Shown"}),
                json!({"type":"message","id":"b","parentId":"shown","message":{"role":"bashExecution","command":"false","output":"boom","exitCode":1,"cancelled":false,"truncated":false}}),
            ],
        );
        let mut provider = Pi {
            roots: SourceRoots::fixed(
                directory.path().into(),
                "agent/sessions",
                "data/pi",
                "PI_HOME/agent/sessions",
            ),
        };
        let discovery = provider.discover(None, &mut |_| Ok(())).unwrap();
        let session = &discovery.sessions[0];
        let data = serde_json::to_value(
            provider.read(session, false, &mut |_| Ok(())).unwrap(),
        )
        .unwrap();
        let messages = data["messages"].as_array().unwrap();
        let roles: Vec<_> =
            messages.iter().map(|message| &message["role"]).collect();
        assert_eq!(roles, ["user", "assistant", "custom", "tool"]);
        let call = &messages[1]["parts"][0]["state"];
        assert_eq!(call["output"][0]["text"], "Result");
        assert_eq!(call["status"], "completed");
        assert_eq!(call["metadata"], json!({"lines": 1}));
        assert_eq!(
            messages[1]["tokens"],
            json!({"input":115,"output":20,"cache":{"read":10,"write":5},"total":135})
        );
        let bash = &messages[3]["parts"][0]["state"];
        assert_eq!(bash["status"], "error");
        assert_eq!(
            bash["metadata"],
            json!({"exitCode":1,"cancelled":false,"truncated":false})
        );
        assert_eq!(
            data["stats"],
            json!({"total_cost":0.25,"total_input_tokens":115,"total_output_tokens":20,"total_tokens":135,"message_count":4})
        );
    }

    #[test]
    fn titles_prefer_session_info_title_record_header_then_prompt() {
        let header = json!({"type":"session","title":"Header"});
        let prompt = json!({"type":"message","id":"u","parentId":null,"message":{"role":"user","content":"<system-reminder>x</system-reminder>\n  First   line \nSecond"}});
        let slot = json!({"type":"title","title":"Slot"});
        let named = json!({"type":"session_info","id":"n","parentId":"u","name":"Named"});
        for (records, expected) in [
            (
                vec![json!({"type":"session"}), prompt.clone()],
                "First line",
            ),
            (vec![header.clone(), prompt.clone()], "Header"),
            (vec![slot.clone(), header.clone(), prompt.clone()], "Slot"),
            (vec![header, prompt, slot, named], "Named"),
        ] {
            let transcript =
                transcript::Transcript::new(records, |_| Ok(())).unwrap();
            assert_eq!(transcript.title.as_deref(), Some(expected));
        }
    }

    #[test]
    fn source_selection_retries_absence_and_keeps_selected_root() {
        crate::providers::source_tests::source_selection(
            "agent/sessions",
            false,
            |roots| Pi { roots },
            |base| {
                let path = base.join("kept.jsonl");
                std::fs::create_dir_all(base).unwrap();
                std::fs::write(
                    &path,
                    concat!(
                        r#"{"type":"session","id":"kept","timestamp":"2026-01-15T00:00:00Z"}"#,
                        "\n",
                        r#"{"type":"message","message":{"role":"user","content":"Keep"}}"#,
                        "\n"
                    ),
                )
                .unwrap();
                path
            },
        );
    }

    #[test]
    fn removed_source_keeps_provider_diagnostic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("agent/sessions/kept.jsonl");
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(
            &path,
            "{\"type\":\"session\",\"id\":\"kept\",\"timestamp\":\"2026-01-15T00:00:00Z\"}\n",
        )
        .unwrap();
        let provider = Pi {
            roots: SourceRoots::fixed(
                directory.path().into(),
                "agent/sessions",
                "data/pi",
                "PI_HOME/agent/sessions",
            ),
        };
        crate::providers::source_tests::removed_file(
            provider,
            &path,
            "kept",
            "Pi session directory",
        );
    }
}
