use agent_dump_core::output::diagnostics::{self, Diagnostic};
use agent_dump_core::output::export;
use agent_dump_core::output::formats::OutputFormat;
use agent_dump_core::output::render;
use agent_dump_core::providers::contract::{RawExport, render_search_roots};
use agent_dump_core::providers::registry;
use std::io::Write;
use std::path::PathBuf;

pub struct UriOperation {
    pub uri: String,
    pub head: bool,
    pub summary: bool,
    pub formats: Vec<OutputFormat>,
    pub output: Option<PathBuf>,
}

pub fn run(
    operation: &UriOperation,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let uri = &operation.uri;
    let Some((registration, id)) = registry::for_uri(uri) else {
        write!(
            out,
            "{}",
            Diagnostic::invalid_uri(uri, registry::uri_examples(), zh)
                .render(zh)
        )?;
        return Ok(false);
    };
    let found = (registration.open)().and_then(|mut provider| {
        let lookup = provider.find(id, &mut |diagnostic| {
            writeln!(
                warnings,
                "{}",
                diagnostics::record_warning(&diagnostic, zh)
            )?;
            Ok(())
        })?;
        Ok((provider, lookup))
    });
    let found = match found {
        Ok((provider, lookup)) => {
            for failure in &lookup.failures {
                writeln!(
                    warnings,
                    "{}",
                    diagnostics::session_warning(
                        &registration.info,
                        failure,
                        zh
                    )
                )?;
            }
            lookup.session.map(|session| (provider, session))
        }
        Err(error) => {
            writeln!(
                warnings,
                "{}",
                diagnostics::lookup_warning(
                    &registration.info,
                    error.as_ref(),
                    zh
                )
            )?;
            None
        }
    };
    let Some((provider, session)) = found else {
        let roots = match registry::search_roots() {
            Ok(roots) => roots,
            Err(error) => {
                write!(
                    out,
                    "{}",
                    Diagnostic::unexpected(error.as_ref(), zh).render(zh)
                )?;
                return Ok(false);
            }
        };
        write!(
            out,
            "{}",
            Diagnostic::missing_session(
                uri,
                registration.info.scheme,
                id,
                roots,
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
    let default_output = if operation.output.is_none()
        && operation
            .formats
            .iter()
            .any(|f| matches!(f, OutputFormat::Json | OutputFormat::Raw))
    {
        let config = agent_dump_core::config::Config::load()?;
        if let Err(error) = config.require_valid(zh) {
            writeln!(out, "{error}")?;
            return Ok(false);
        }
        config.output()
    } else {
        String::new()
    };
    let raw = provider.raw_export(&session);
    let cache = agent_dump_core::session::cache::SessionDataCache::default();
    let prepared = (operation
        .formats
        .iter()
        .any(|format| *format != OutputFormat::Raw)
        || matches!(raw, Ok(RawExport::Session)))
    .then(|| {
        cache.get(
            registration.info.name,
            provider.as_ref(),
            &session,
            zh,
            &mut |diagnostic| {
                writeln!(
                    warnings,
                    "{}",
                    diagnostics::record_warning(&diagnostic, zh)
                )?;
                Ok(())
            },
        )
    });
    let summary = if operation.summary {
        generate_summary(
            uri,
            &operation.formats,
            prepared.as_ref(),
            zh,
            out,
            warnings,
        )?
    } else {
        None
    };
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
        let needs_data = *format != OutputFormat::Raw
            || matches!(raw, Ok(RawExport::Session));
        let error = match (&raw, &prepared) {
            (Err(error), _) if *format == OutputFormat::Raw => Some(error),
            (_, Some(Err(error))) if needs_data => Some(error),
            _ => None,
        };
        if let Some(error) = error {
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
        let data = prepared
            .as_ref()
            .and_then(|result| result.as_ref().ok())
            .map(std::convert::AsRef::as_ref);
        let output = export::output_base(
            operation.output.as_deref(),
            &default_output,
            *format,
        )
        .join(registration.info.name);
        let result = export::SessionExport {
            provider: provider.as_ref(),
            session: &session,
            uri,
            data,
            raw: &raw,
        }
        .write(*format, &output, summary.as_deref());
        match result {
            Ok(path) => {
                let path = render::safe_line(
                    &agent_dump_core::storage::source_io::path_text(&path),
                );
                if *format == OutputFormat::Json && summary.is_some() {
                    writeln!(
                        out,
                        "{}",
                        agent_dump_core::output::i18n::terminal(
                            "URI_SUMMARY_APPLIED",
                            zh,
                            &[("path", path.clone())]
                        )
                    )?;
                }
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

fn generate_summary(
    uri: &str,
    formats: &[OutputFormat],
    prepared: Option<
        &crate::Result<std::sync::Arc<agent_dump_core::session::SessionData>>,
    >,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<Option<String>> {
    use agent_dump_core::output::i18n::{t, terminal};
    if !formats.contains(&OutputFormat::Json) {
        writeln!(out, "{}", t("URI_SUMMARY_NO_JSON_WARNING", zh, &[]))?;
        return Ok(None);
    }
    let mut prepare = || -> crate::Result<Option<(agent_dump_core::config::AiConfig, String)>> {
        let config = agent_dump_core::config::Config::load()?;
        config.require_valid(zh)?;
        let ai = config.ai();
        let errors = agent_dump_core::config::validate_ai(ai.as_ref(), config.exists);
        if !errors.is_empty() {
            let key = if errors.contains(&"missing_file") {
                "URI_SUMMARY_CONFIG_MISSING_WARNING"
            } else if errors.contains(&"base_url_scheme") {
                "COLLECT_CONFIG_BAD_SCHEME"
            } else if errors.contains(&"base_url_plaintext_key") {
                "COLLECT_CONFIG_PLAINTEXT_KEY"
            } else {
                "URI_SUMMARY_CONFIG_INCOMPLETE_WARNING"
            };
            writeln!(
                out,
                "{}",
                terminal(key, zh, &[("fields", errors.join(","))])
            )?;
            return Ok(None);
        }
        let data = prepared
            .unwrap()
            .as_ref()
            .map_err(std::string::ToString::to_string)?;
        Ok(Some((
            ai.unwrap(),
            crate::collect::prompts::uri_summary(uri, &render::transcript(uri, data)),
        )))
    };
    let (ai, prompt) = match prepare() {
        Ok(Some(prepared)) => prepared,
        Ok(None) => return Ok(None),
        Err(error) => {
            writeln!(
                out,
                "{}",
                terminal(
                    "URI_SUMMARY_PREPARATION_FAILED_WARNING",
                    zh,
                    &[("error", error.to_string())]
                )
            )?;
            return Ok(None);
        }
    };
    writeln!(warnings, "{}", t("URI_SUMMARY_LOADING", zh, &[]))?;
    match crate::collect::llm::summary(&ai, &prompt, 90) {
        Ok(summary) => Ok(Some(summary)),
        Err(error) => {
            writeln!(
                out,
                "{}",
                terminal(
                    "URI_SUMMARY_API_FAILED_WARNING",
                    zh,
                    &[("error", error.to_string())]
                )
            )?;
            Ok(None)
        }
    }
}
