use crate::cli_args::Args;
use crate::{
    Result, collect_model, collect_workflow, config_command, diagnostics, i18n, list_workflow,
    maintenance, output_formats, query, query_text, render, uri_workflow,
};
use std::io::{self, Write};
#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Providers,
    Config,
    Collect,
    Stats,
    Reindex,
    Uri,
    List,
    Interactive,
    Help,
}
fn candidates(args: &Args) -> Vec<(Mode, &'static str)> {
    let query_uri = args
        .uri
        .as_deref()
        .is_some_and(|s| s.starts_with("agents://"));
    let mut result = Vec::new();
    for (present, mode, label) in [
        (args.providers, Mode::Providers, "--providers"),
        (args.config.is_some(), Mode::Config, "--config"),
        (args.collect, Mode::Collect, "--collect"),
        (args.stats, Mode::Stats, "--stats"),
        (args.reindex, Mode::Reindex, "--reindex"),
        (
            args.uri.as_ref().is_some_and(|s| !s.is_empty()) && !query_uri,
            Mode::Uri,
            "session URI",
        ),
        (
            args.search.as_ref().is_some_and(|s| !s.is_empty()),
            Mode::List,
            "--search",
        ),
        (args.list, Mode::List, "--list"),
        (args.interactive, Mode::Interactive, "--interactive"),
        (
            query_uri && !args.collect,
            Mode::List,
            "agents:// query URI",
        ),
    ] {
        if present {
            result.push((mode, label));
        }
    }
    if (!query_uri || args.collect)
        && (args.days.is_some() || args.query.as_ref().is_some_and(|s| !s.is_empty()))
    {
        result.push((Mode::List, ""));
    }
    if result.is_empty() {
        result.push((Mode::Help, ""));
    }
    result
}
fn mode(args: &Args) -> Mode {
    candidates(args)[0].0
}

pub fn run(args: Args, out: &mut impl Write) -> Result<bool> {
    let zh = args.lang.as_deref().map_or_else(
        || {
            ["LC_ALL", "LC_MESSAGES", "LANG"]
                .iter()
                .find_map(|key| std::env::var(key).ok().filter(|v| !v.is_empty()))
                .is_some_and(|v| v.starts_with("zh"))
        },
        |lang| lang == "zh",
    );
    let mut plan_stderr = io::stderr();
    let plan_out: &mut dyn Write = if args.emit_prompt {
        &mut plan_stderr
    } else {
        out
    };
    let mode = mode(&args);
    let query_uri_requested = args
        .uri
        .as_deref()
        .is_some_and(|s| s.starts_with("agents://"));
    let error_key = if args.emit_prompt && mode != Mode::Collect {
        Some("EMIT_PROMPT_REQUIRES_COLLECT")
    } else if args.emit_prompt && args.dry_run {
        Some("COLLECT_ACTION_CONFLICT")
    } else if mode == Mode::Collect
        && (args.list || args.interactive || (args.uri.is_some() && !query_uri_requested))
    {
        Some("COLLECT_MODE_CONFLICT")
    } else if mode == Mode::Uri && args.head && args.summary && args.format.is_none() {
        Some("URI_HEAD_WITH_SUMMARY_ERROR")
    } else {
        None
    };
    if let Some(key) = error_key {
        if args.emit_prompt {
            eprintln!("{}", i18n::t(key, zh, &[]));
        } else {
            writeln!(plan_out, "{}", i18n::t(key, zh, &[]))?;
        }
        return Ok(false);
    }
    if mode != Mode::Uri && mode != Mode::Providers {
        for (present, key) in [
            (args.summary, "SUMMARY_IGNORED_NON_URI_WARNING"),
            (args.head, "HEAD_IGNORED_NON_URI_WARNING"),
        ] {
            if present {
                writeln!(plan_out, "{}", i18n::t(key, zh, &[]))?;
            }
        }
    }
    let ignored: Vec<_> = candidates(&args)
        .into_iter()
        .filter(|(candidate, _)| *candidate != mode)
        .map(|(_, label)| label)
        .filter(|s| !s.is_empty())
        .collect();
    if !ignored.is_empty() {
        writeln!(
            plan_out,
            "{}",
            i18n::terminal(
                "CLI_MODE_OPTIONS_IGNORED_WARNING",
                zh,
                &[("options", ignored.join(", "))]
            )
        )?;
    }
    if mode == Mode::Providers {
        return maintenance::providers(zh, out);
    }
    if let Some(action) = &args.config {
        return config_command::run(action, zh, out, &mut io::stdin().lock());
    }
    if matches!(
        mode,
        Mode::Collect | Mode::Stats | Mode::Reindex | Mode::List | Mode::Interactive
    ) && let Some(days) = args.days
    {
        let maximum = jiff::Zoned::now()
            .date()
            .since((jiff::Unit::Day, jiff::civil::date(1, 1, 1)))?
            .get_days() as i64
            + 1;
        if days <= 0 || days >= maximum {
            return Err(clap::Error::raw(
                clap::error::ErrorKind::ValueValidation,
                i18n::t("CLI_DAYS_INVALID", zh, &[("value", days.to_string())]),
            )
            .into());
        }
    }
    let query_uri = args.uri.as_deref().filter(|uri| {
        uri.starts_with("agents://")
            && matches!(mode, Mode::Collect | Mode::List | Mode::Interactive)
    });
    if query_uri.is_some() && args.query.is_some() {
        write!(
            plan_out,
            "{}",
            diagnostics::Diagnostic::query_error(
                &i18n::t("DIAG_QUERY_URI_WITH_Q_DETAIL", zh, &[]),
                query_uri,
                true,
                zh
            )
            .render(zh)
        )?;
        return Ok(false);
    }
    let query = if let Some(uri) = query_uri {
        query::Query::from_uri(uri, zh).map(Some)
    } else {
        args.query
            .as_deref()
            .filter(|q| {
                !matches!(mode, Mode::Uri | Mode::Reindex) && (mode != Mode::Stats || !q.is_empty())
            })
            .map(|raw| query::Query::parse(raw, zh))
            .transpose()
    };
    let mut query = match query {
        Ok(query) => query,
        Err(error) => {
            write!(
                plan_out,
                "{}",
                diagnostics::Diagnostic::query_error(&error.to_string(), query_uri, false, zh)
                    .render(zh)
            )?;
            return Ok(false);
        }
    };
    if mode == Mode::Collect {
        return collect_workflow::run(
            collect_model::Operation {
                days: args.days,
                since: args.since,
                until: args.until,
                save: args.save,
                mode: args.collect_mode,
                action: if args.emit_prompt {
                    collect_model::Action::EmitPrompt
                } else if args.dry_run {
                    collect_model::Action::DryRun
                } else {
                    collect_model::Action::Execute
                },
                query,
            },
            zh,
            out,
            &mut io::stderr(),
        );
    }
    if matches!(mode, Mode::Stats | Mode::Reindex) {
        return maintenance::run(
            query,
            args.days.unwrap_or(7),
            mode == Mode::Reindex,
            zh,
            out,
            &mut io::stderr(),
        );
    }
    if let Some(search) = args
        .search
        .as_ref()
        .filter(|s| !s.is_empty() && mode == Mode::List)
    {
        let query = query.get_or_insert_with(query::Query::default);
        query.keyword = Some(search.clone());
        query.mode = query_text::Mode::Terms;
    }
    if mode == Mode::List {
        if let Some(spec) = &args.format {
            output_formats::parse(spec).map_err(|_| {
                clap::Error::raw(
                    clap::error::ErrorKind::ValueValidation,
                    i18n::t("CLI_FORMAT_INVALID", zh, &[("value", spec.clone())]),
                )
            })?;
        }
        return list_workflow::run(
            query,
            args.days.unwrap_or(7),
            !args.no_metadata_summary,
            (args.format.is_some(), args.output.is_some()),
            zh,
            out,
            &mut io::stderr(),
        );
    }
    if mode == Mode::Interactive {
        let formats = output_formats::parse(args.format.as_deref().unwrap_or("json"))?;
        if formats.contains(&output_formats::OutputFormat::Print) {
            write!(
                out,
                "{}",
                diagnostics::Diagnostic::interactive_print(zh).render(zh)
            )?;
            return Ok(false);
        }
        return crate::interactive_workflow::run(
            crate::interactive_workflow::Operation {
                query,
                days: args.days.unwrap_or(7),
                formats,
                output: args.output,
                metadata: !args.no_metadata_summary,
            },
            zh,
            out,
            &mut io::stderr(),
            &mut io::stdin().lock(),
        );
    }
    if mode == Mode::Help {
        crate::cli_args::command(zh).print_help()?;
        writeln!(out)?;
        return Ok(true);
    }
    let uri = args.uri.ok_or("Provide a session URI or --list")?;
    if args.head && args.format.is_some() {
        writeln!(
            out,
            "{}",
            if zh {
                "❌ --head 不能与 -format/--format 同时使用。"
            } else {
                "❌ --head cannot be used with -format/--format."
            }
        )?;
        return Ok(false);
    }
    let formats = if args.head {
        Vec::new()
    } else {
        let spec = args.format.as_deref().unwrap_or("print");
        output_formats::parse(spec).map_err(|_| {
            let spec = render::safe_line(spec);
            clap::Error::raw(
                clap::error::ErrorKind::ValueValidation,
                if zh {
                    format!("无效的格式列表: {spec}")
                } else {
                    format!("Invalid format list: {spec}")
                },
            )
        })?
    };
    uri_workflow::run(
        uri_workflow::UriOperation {
            uri,
            head: args.head,
            summary: args.summary,
            formats,
            output: args.output,
        },
        zh,
        out,
        &mut io::stderr(),
    )
}
