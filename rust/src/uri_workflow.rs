use crate::output_formats::OutputFormat;
use crate::registry;
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
    let (registration, id) = registry::for_uri(uri)?;
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
    let mut provider = (registration.open)()?;
    let session = provider.find(id)?;
    if operation.head {
        write!(
            out,
            "{}",
            render::head(uri, &session, registration.info.display_name, zh)
        )?;
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
        let output = operation
            .output
            .as_ref()
            .unwrap()
            .join(registration.info.name);
        let result = if *format == OutputFormat::Raw {
            provider.raw_source(&session).and_then(|source| {
                export::raw(&session.id, &source, &output, provider.source_root())
            })
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
