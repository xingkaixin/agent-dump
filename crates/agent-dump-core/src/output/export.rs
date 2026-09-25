use sha2::{Digest, Sha256};
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};

fn filename(id: &str) -> crate::Result<String> {
    let normalized = id.replace('\\', "/");
    let name = normalized
        .rsplit('/')
        .find(|component| !component.is_empty() && *component != ".")
        .unwrap_or("");
    let reason = if matches!(name, "" | "." | "..") {
        Some("no usable filename component")
    } else if crate::output::render::safe_body(name) != name
        || name.contains(['\t', '\n'])
    {
        Some("filename contains a control character")
    } else {
        None
    };
    if let Some(reason) = reason {
        return Err(crate::providers::error::ProviderError::Diagnostic {
            summary: ["session id cannot be used as an export filename"; 2],
            details: vec![
                format!("session id: {}", crate::compat::value::repr(&id.into())),
                format!("reason: {reason}"),
            ],
            roots: Vec::new(),
            capability: Some(["session id does not produce a safe filename"; 2]),
            next_steps: vec![[
                "Pick another session, or fix the session id in the provider data.",
                "选择其他会话，或修复 provider 数据中的 session id。",
            ]],
        }
        .into());
    }
    let edge = |c: char| {
        c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-'
    };
    let stem = name.split('.').next().unwrap_or("");
    let reserved = matches!(stem, "aux" | "con" | "nul" | "prn")
        || (1..=9)
            .any(|i| stem == format!("com{i}") || stem == format!("lpt{i}"));
    if id == name
        && id.len() <= 120
        && id.starts_with(edge)
        && id.ends_with(edge)
        && id.chars().all(|c| edge(c) || c == '.')
        && !reserved
    {
        Ok(id.to_owned())
    } else {
        Ok(format!("~{:x}", Sha256::digest(id.as_bytes())))
    }
}

fn absolute_existing_ancestor(path: &Path) -> crate::Result<PathBuf> {
    if path.exists() {
        return Ok(path.canonicalize()?);
    }
    let parent = path.parent().ok_or("Cannot resolve output path")?;
    Ok(absolute_existing_ancestor(parent)?
        .join(path.file_name().ok_or("Invalid output path")?))
}

fn write(
    output: &Path,
    session_id: &str,
    suffix: &str,
    source_root: &Path,
    contents: impl FnOnce(&mut fs::File) -> crate::Result<()>,
) -> crate::Result<PathBuf> {
    let directory = std::path::absolute(output)?;
    let resolved = absolute_existing_ancestor(&directory)?;
    if resolved.starts_with(source_root.canonicalize()?) {
        return Err(
            "Export output must be outside the Provider source directory"
                .into(),
        );
    }
    let output_path = output.join(format!("{}{suffix}", filename(session_id)?));
    let destination = std::path::absolute(&output_path)?;
    if destination.is_symlink() {
        return Err("Export destination must not be a symlink".into());
    }
    crate::storage::private_files::ensure_directory(output)?;
    let mut temporary = tempfile::Builder::new()
        .prefix(&format!(
            ".{}.",
            output_path.file_name().unwrap().to_string_lossy()
        ))
        .suffix(".tmp")
        .rand_bytes(8)
        .tempfile_in(&directory)?;
    contents(temporary.as_file_mut())?;
    temporary.flush()?;
    crate::storage::private_files::sync(temporary.as_file())?;
    temporary.persist(&destination).map_err(|error| {
        crate::storage::source_io::Error::rename(
            error.file.path(),
            &output_path,
            &error.error,
        )
    })?;
    Ok(output_path)
}

pub fn json(
    session_id: &str,
    data: &impl serde::Serialize,
    output: &Path,
    source_root: &Path,
    suffix: &str,
) -> crate::Result<PathBuf> {
    write(output, session_id, suffix, source_root, |file| {
        let mut writer = io::BufWriter::new(file);
        data.serialize(&mut serde_json::Serializer::with_formatter(
            &mut writer,
            crate::compat::json::Formatter::default(),
        ))?;
        writer.flush()?;
        Ok(())
    })
}

pub fn markdown(
    session_id: &str,
    text: &str,
    output: &Path,
    source_root: &Path,
) -> crate::Result<PathBuf> {
    write(output, session_id, ".md", source_root, |file| {
        if cfg!(windows) {
            file.write_all(text.replace('\n', "\r\n").as_bytes())?;
        } else {
            file.write_all(text.as_bytes())?;
        }
        Ok(())
    })
}

pub fn raw(
    session_id: &str,
    source: &Path,
    output: &Path,
    source_root: &Path,
) -> crate::Result<PathBuf> {
    write(output, session_id, ".raw.jsonl", source_root, |file| {
        io::copy(&mut fs::File::open(source)?, file)?;
        Ok(())
    })
}

pub struct SessionExport<'a> {
    pub provider: &'a dyn crate::providers::contract::Provider,
    pub session: &'a crate::session::Session,
    pub uri: &'a str,
    pub data: Option<&'a crate::session::SessionData>,
    pub raw: &'a crate::Result<crate::providers::contract::RawExport>,
}
impl SessionExport<'_> {
    pub fn write(
        &self,
        format: crate::output::formats::OutputFormat,
        output: &Path,
        summary: Option<&str>,
    ) -> crate::Result<PathBuf> {
        use crate::output::formats::OutputFormat;
        use crate::providers::contract::RawExport;
        match format {
            OutputFormat::Raw => match self.raw.as_ref().unwrap() {
                RawExport::File(source) => raw(
                    &self.session.id,
                    source,
                    output,
                    self.provider.source_root(),
                ),
                RawExport::Session => json(
                    &self.session.id,
                    self.data.unwrap(),
                    output,
                    self.provider.source_root(),
                    ".raw.json",
                ),
            },
            OutputFormat::Json => {
                let mut payload =
                    self.provider.json_payload(self.data.unwrap());
                if let Some(summary) = summary
                    && let Some(object) = payload.as_object_mut()
                {
                    object.insert("summary".into(), summary.into());
                }
                json(
                    &self.session.id,
                    &payload,
                    output,
                    self.provider.source_root(),
                    ".json",
                )
            }
            OutputFormat::Markdown => markdown(
                &self.session.id,
                &crate::output::render::transcript(
                    self.uri,
                    self.data.unwrap(),
                ),
                output,
                self.provider.source_root(),
            ),
            OutputFormat::Print => unreachable!(),
        }
    }
}

pub fn output_base(
    explicit: Option<&Path>,
    configured: &str,
    format: crate::output::formats::OutputFormat,
) -> PathBuf {
    explicit.filter(|p| !p.as_os_str().is_empty()).map_or_else(
        || {
            if explicit.is_none()
                && matches!(
                    format,
                    crate::output::formats::OutputFormat::Json
                        | crate::output::formats::OutputFormat::Raw
                )
                && !configured.is_empty()
            {
                configured.into()
            } else {
                "sessions".into()
            }
        },
        Path::to_path_buf,
    )
}

pub fn target(
    id: &str,
    output: &Path,
    format: crate::output::formats::OutputFormat,
    raw: Option<&crate::providers::contract::RawExport>,
) -> crate::Result<PathBuf> {
    use crate::output::formats::OutputFormat;
    let suffix = match format {
        OutputFormat::Json => ".json",
        OutputFormat::Markdown => ".md",
        OutputFormat::Raw => {
            if matches!(
                raw,
                Some(crate::providers::contract::RawExport::Session)
            ) {
                ".raw.json"
            } else {
                ".raw.jsonl"
            }
        }
        OutputFormat::Print => unreachable!(),
    };
    Ok(output.join(format!("{}{suffix}", filename(id)?)))
}
