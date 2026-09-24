use crate::codex::Codex;
use crate::output_formats::OutputFormat;
use crate::{export, render};
use std::io::Write;
use std::path::PathBuf;

pub struct UriOperation {
    pub uri: String,
    pub head: bool,
    pub formats: Vec<OutputFormat>,
    pub output: Option<PathBuf>,
}

pub fn run(operation: UriOperation, zh: bool, out: &mut impl Write) -> crate::Result<bool> {
    let uri = &operation.uri;
    let id = uri
        .strip_prefix("codex://")
        .ok_or("Rust currently only supports codex:// URIs")?;
    let id = id.strip_prefix("threads/").unwrap_or(id);
    if id.is_empty() {
        return Err("Empty Codex session id".into());
    }
    if operation
        .formats
        .iter()
        .any(|format| *format != OutputFormat::Print)
        && operation.output.is_none()
    {
        return Err(
            "Rust file export requires --output; configuration defaults are not implemented yet"
                .into(),
        );
    }
    let provider = Codex::open()?;
    let session = provider.find(id)?;
    if operation.head {
        write!(out, "{}", render::head(uri, &session, zh))?;
        return Ok(true);
    }
    let prepared = operation
        .formats
        .iter()
        .any(|format| *format != OutputFormat::Raw)
        .then(|| provider.read(&session, zh));
    let mut success = false;
    if operation.formats.contains(&OutputFormat::Print) {
        match prepared.as_ref().unwrap() {
            Ok(data) => {
                writeln!(out, "{}", render::transcript(uri, data))?;
                success = true;
            }
            Err(error) => eprintln!("Error: {}", render::safe_line(&error.to_string())),
        }
    }
    for format in operation
        .formats
        .iter()
        .filter(|format| **format != OutputFormat::Print)
    {
        let output = operation.output.as_ref().unwrap().join("codex");
        let result = if *format == OutputFormat::Raw {
            export::raw(&session, &output, provider.source_root())
        } else {
            match prepared.as_ref().unwrap() {
                Ok(data) if *format == OutputFormat::Json => export::json(
                    &provider.json_payload(data),
                    &output,
                    provider.source_root(),
                ),
                Ok(data) => export::markdown(
                    &session.id,
                    &render::transcript(uri, data),
                    &output,
                    provider.source_root(),
                ),
                Err(error) => Err(error.to_string().into()),
            }
        };
        match result {
            Ok(path) => {
                let path = render::safe_line(&path.display().to_string());
                let format = format.name();
                writeln!(
                    out,
                    "{}",
                    if zh {
                        format!("✅ 已导出 [{format}] 到: {path}")
                    } else {
                        format!("✅ Exported session [{format}] to: {path}")
                    }
                )?;
                success = true;
            }
            Err(error) => eprintln!("Error: {}", render::safe_line(&error.to_string())),
        }
    }
    Ok(success)
}
