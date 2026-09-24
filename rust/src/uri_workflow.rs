use crate::diagnostics::{self, Diagnostic};
use crate::output_formats::OutputFormat;
use crate::provider::{RawExport, render_search_roots};
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

pub fn run(
    operation: UriOperation,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let uri = &operation.uri;
    let Some((registration, id)) = registry::for_uri(uri) else {
        write!(
            out,
            "{}",
            Diagnostic::invalid_uri(uri, registry::uri_examples(), zh).render(zh)
        )?;
        return Ok(false);
    };
    let found = (registration.open)().and_then(|mut provider| {
        let lookup = provider.find(id)?;
        Ok((provider, lookup))
    });
    let found = match found {
        Ok((provider, lookup)) => {
            for failure in &lookup.failures {
                writeln!(
                    warnings,
                    "{}",
                    diagnostics::session_warning(&registration.info, failure, zh)
                )?;
            }
            lookup.session.map(|session| (provider, session))
        }
        Err(error) => {
            writeln!(
                warnings,
                "{}",
                diagnostics::lookup_warning(&registration.info, error.as_ref(), zh)
            )?;
            None
        }
    };
    let Some((provider, session)) = found else {
        write!(
            out,
            "{}",
            Diagnostic::missing_session(
                uri,
                registration.info.scheme,
                id,
                registry::search_roots(),
                zh
            )
            .render(zh)
        )?;
        return Ok(false);
    };
    if let Some(diagnostic) = Diagnostic::unsupported_formats(
        &registration.info,
        provider.as_ref(),
        &operation.formats,
        zh,
    ) {
        write!(out, "{}", diagnostic.render(zh))?;
        return Ok(false);
    }
    if operation.head {
        write!(
            out,
            "{}",
            render::head(uri, &session, registration.info.display_name, zh)
        )?;
        return Ok(true);
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
    let raw = provider.raw_export(&session);
    let prepared = (operation
        .formats
        .iter()
        .any(|format| *format != OutputFormat::Raw)
        || matches!(raw, RawExport::Session))
    .then(|| provider.read(&session, zh));
    let mut success = false;
    if operation.formats.contains(&OutputFormat::Print) {
        match prepared.as_ref().unwrap() {
            Ok(data) => {
                writeln!(out, "{}", render::transcript(uri, data))?;
                success = true;
            }
            Err(error) => write!(
                out,
                "{}",
                Diagnostic::read_failed(
                    error.as_ref(),
                    render_search_roots(&registration.info, provider.as_ref()),
                    zh
                )
                .render(zh)
            )?,
        }
    }
    for format in operation
        .formats
        .iter()
        .filter(|format| **format != OutputFormat::Print)
    {
        if (*format != OutputFormat::Raw || matches!(raw, RawExport::Session))
            && let Some(Err(error)) = &prepared
        {
            write!(
                out,
                "{}",
                Diagnostic::read_failed(
                    error.as_ref(),
                    render_search_roots(&registration.info, provider.as_ref()),
                    zh
                )
                .render(zh)
            )?;
            continue;
        }
        let data = prepared.as_ref().and_then(|result| result.as_ref().ok());
        let output = operation
            .output
            .as_ref()
            .unwrap()
            .join(registration.info.name);
        let result = if *format == OutputFormat::Raw {
            match &raw {
                RawExport::File(source) => {
                    export::raw(&session.id, source, &output, provider.source_root())
                }
                RawExport::Session => export::json(
                    &session.id,
                    data.unwrap(),
                    &output,
                    provider.source_root(),
                    ".raw.json",
                ),
            }
        } else if *format == OutputFormat::Json {
            export::json(
                &session.id,
                &provider.json_payload(data.unwrap()),
                &output,
                provider.source_root(),
                ".json",
            )
        } else {
            export::markdown(
                &session.id,
                &render::transcript(uri, data.unwrap()),
                &output,
                provider.source_root(),
            )
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
            Err(error) => write!(
                out,
                "{}",
                Diagnostic::read_failed(
                    error.as_ref(),
                    render_search_roots(&registration.info, provider.as_ref()),
                    zh
                )
                .render(zh)
            )?,
        }
    }
    Ok(success)
}
