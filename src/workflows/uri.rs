use agent_dump_core::output::diagnostics::{self, Diagnostic};
use agent_dump_core::output::export;
use agent_dump_core::output::formats::OutputFormat;
use agent_dump_core::output::render;
use agent_dump_core::providers::contract::{
    Provider, ProviderInfo, RawExport, render_search_roots,
};
use agent_dump_core::providers::registry::{self, Registration};
use agent_dump_core::session::{Session, SessionData};
use std::io::Write;
use std::ops::Range;
use std::path::{Path, PathBuf};

pub enum ReadOperation {
    Prompt,
    Page(agent_dump_core::query::read::Request),
}

pub struct UriOperation {
    pub uri: String,
    pub head: bool,
    pub summary: bool,
    pub message: Option<String>,
    pub before: usize,
    pub after: usize,
    pub json: bool,
    pub read: Option<ReadOperation>,
    pub formats: Vec<OutputFormat>,
    pub output: Option<PathBuf>,
}

pub fn run(
    operation: &UriOperation,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    if !operation.json && operation.read.is_none() {
        return run_inner(operation, zh, out, warnings);
    }
    let mut buffer = Vec::new();
    let success = run_inner(operation, zh, &mut buffer, warnings)?;
    if success {
        out.write_all(&buffer)?;
    } else {
        warnings.write_all(&buffer)?;
    }
    Ok(success)
}

fn run_inner(
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
    if matches!(&operation.read, Some(ReadOperation::Prompt)) {
        write!(out, "{}", super::read::prompt(uri, zh)?)?;
        return Ok(true);
    }
    let mut incomplete = false;
    let Some((provider, session)) =
        find(registration, id, &mut incomplete, zh, warnings)?
    else {
        let diagnostic = match registry::search_roots() {
            Ok(roots) => Diagnostic::missing_session(
                uri,
                registration.info.scheme,
                id,
                roots,
                zh,
            ),
            Err(error) => Diagnostic::unexpected(error.as_ref(), zh),
        };
        write!(out, "{}", diagnostic.render(zh))?;
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
        return head(
            operation,
            &registration.info,
            &session,
            incomplete,
            zh,
            out,
        );
    }
    if let Some(ReadOperation::Page(request)) = &operation.read {
        let data =
            read(provider.as_ref(), &session, &mut incomplete, zh, warnings)?;
        let uri = format!("{}://{id}", registration.info.scheme);
        let page =
            agent_dump_core::query::read::page(&uri, &data, request, zh)?;
        super::read::write_page(&page, operation.json, incomplete, zh, out)?;
        return Ok(true);
    }
    let Some(locator) = &operation.message else {
        return export(
            operation,
            &registration.info,
            provider.as_ref(),
            &session,
            zh,
            out,
            warnings,
        );
    };
    let Some(default_output) = default_output(operation, zh, out)? else {
        return Ok(false);
    };
    let data =
        read(provider.as_ref(), &session, &mut incomplete, zh, warnings)?;
    let range = agent_dump_core::query::context::window(
        &data,
        locator,
        operation.before,
        operation.after,
        zh,
    )?;
    if operation.formats.contains(&OutputFormat::Print) {
        return print_excerpt(
            operation, locator, &data, range, incomplete, zh, out,
        );
    }
    let canonical_uri =
        format!("{}://{}", registration.info.scheme, session.id);
    let excerpt = export::Excerpt {
        uri: &canonical_uri,
        locator,
        data: &data,
        range,
        incomplete,
    };
    let output =
        export::output_base(operation.output.as_deref(), &default_output)
            .join(registration.info.name);
    export_excerpt(&excerpt, &operation.formats, &output, zh, out)
}

fn find(
    registration: &Registration,
    id: &str,
    incomplete: &mut bool,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Option<(Box<dyn Provider>, Session)>> {
    let found = (registration.open)().and_then(|mut provider| {
        let lookup = provider.find(id, &mut |diagnostic| {
            *incomplete = true;
            writeln!(
                warnings,
                "{}",
                diagnostics::record_warning(&diagnostic, zh)
            )?;
            Ok(())
        })?;
        Ok((provider, lookup))
    });
    match found {
        Ok((provider, lookup)) => {
            for failure in &lookup.failures {
                *incomplete = true;
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
            Ok(lookup.session.map(|session| (provider, session)))
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
            Ok(None)
        }
    }
}

fn read(
    provider: &dyn Provider,
    session: &Session,
    incomplete: &mut bool,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<SessionData> {
    provider.read(session, zh, &mut |diagnostic| {
        *incomplete = true;
        writeln!(warnings, "{}", diagnostics::record_warning(&diagnostic, zh))?;
        Ok(())
    })
}

fn head(
    operation: &UriOperation,
    info: &ProviderInfo,
    session: &Session,
    incomplete: bool,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<bool> {
    if operation.json {
        let mut record = super::machine::session_record(info, session);
        record["project"] = serde_json::json!(session.project);
        record["version"] = session.version.clone();
        record["subtargets"] = serde_json::json!(session.subtargets);
        serde_json::to_writer(
            &mut *out,
            &serde_json::json!({
                "schema_version": 1,
                "kind": "head",
                "status": if incomplete { "partial" } else { "ok" },
                "data": record
            }),
        )?;
        writeln!(out)?;
        return Ok(true);
    }
    write!(
        out,
        "{}",
        render::head(&operation.uri, session, info.display_name, zh)
    )?;
    Ok(true)
}

fn default_output(
    operation: &UriOperation,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<Option<String>> {
    if operation.output.is_some()
        || operation.formats.iter().all(|f| *f == OutputFormat::Print)
    {
        return Ok(Some(String::new()));
    }
    let config = agent_dump_core::config::Config::load()?;
    if let Err(error) = config.require_valid(zh) {
        writeln!(out, "{error}")?;
        return Ok(None);
    }
    Ok(Some(config.output()))
}

fn print_excerpt(
    operation: &UriOperation,
    locator: &str,
    data: &SessionData,
    range: Range<usize>,
    incomplete: bool,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<bool> {
    let uri = &operation.uri;
    if operation.json {
        serde_json::to_writer(
            &mut *out,
            &render::context_json(uri, locator, data, range, incomplete),
        )?;
        writeln!(out)?;
    } else {
        writeln!(
            out,
            "{}",
            agent_dump_core::output::i18n::t(
                "MESSAGE_CONTEXT_RANGE",
                zh,
                &[
                    ("start", (range.start + 1).to_string()),
                    ("end", range.end.to_string()),
                    ("total", data.messages.len().to_string())
                ]
            )
        )?;
        writeln!(out, "{}", render::context(uri, data, range))?;
    }
    Ok(true)
}

fn export_excerpt(
    excerpt: &export::Excerpt<'_>,
    formats: &[OutputFormat],
    output: &Path,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<bool> {
    for format in formats {
        let path = excerpt.write(*format, output)?;
        writeln!(
            out,
            "{}",
            agent_dump_core::output::i18n::terminal(
                "MESSAGE_CONTEXT_EXPORTED",
                zh,
                &[
                    ("format", format.name().into()),
                    (
                        "path",
                        agent_dump_core::storage::source_io::path_text(&path)
                    )
                ]
            )
        )?;
    }
    Ok(true)
}

fn export(
    operation: &UriOperation,
    info: &ProviderInfo,
    provider: &dyn Provider,
    session: &Session,
    zh: bool,
    out: &mut impl Write,
    warnings: &mut impl Write,
) -> crate::Result<bool> {
    let Some(default_output) = default_output(operation, zh, out)? else {
        return Ok(false);
    };
    let uri = &operation.uri;
    let raw = provider.raw_export(session);
    let cache = agent_dump_core::session::cache::SessionDataCache::default();
    let prepared = (operation
        .formats
        .iter()
        .any(|format| *format != OutputFormat::Raw)
        || matches!(raw, Ok(RawExport::Session)))
    .then(|| {
        cache.get(info.name, provider, session, zh, &mut |diagnostic| {
            writeln!(
                warnings,
                "{}",
                diagnostics::record_warning(&diagnostic, zh)
            )?;
            Ok(())
        })
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
    let read_failed = |error: &(dyn std::error::Error + 'static)| {
        Diagnostic::read_failed(error, render_search_roots(info, provider), zh)
            .render(zh)
    };
    let mut success = false;
    if operation.formats.contains(&OutputFormat::Print) {
        match prepared.as_ref().unwrap() {
            Ok(data) => {
                writeln!(out, "{}", render::transcript(uri, data))?;
                success = true;
            }
            Err(error) => write!(out, "{}", read_failed(error.as_ref()))?,
        }
    }
    let target = export::SessionExport {
        provider,
        session,
        uri,
        data: prepared
            .as_ref()
            .and_then(|result| result.as_ref().ok())
            .map(std::convert::AsRef::as_ref),
        raw: &raw,
    };
    let output =
        export::output_base(operation.output.as_deref(), &default_output)
            .join(info.name);
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
            write!(out, "{}", read_failed(error.as_ref()))?;
            continue;
        }
        match target.write(*format, &output, summary.as_deref()) {
            Ok(path) => {
                exported(*format, &path, summary.is_some(), zh, out)?;
                success = true;
            }
            Err(error) => write!(out, "{}", read_failed(error.as_ref()))?,
        }
    }
    Ok(success)
}

fn exported(
    format: OutputFormat,
    path: &Path,
    summary: bool,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<()> {
    let path = render::safe_line(
        &agent_dump_core::storage::source_io::path_text(path),
    );
    if format == OutputFormat::Json && summary {
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
    Ok(())
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
    match crate::collect::llm::summary(&ai, &prompt, 90, zh) {
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
