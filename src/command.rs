use crate::Result;
use crate::cli_args::Args;
use crate::collect::model as collect_model;
use crate::workflows::collect as collect_workflow;
use crate::workflows::config as config_command;
use crate::workflows::list as list_workflow;
use crate::workflows::maintenance;
use crate::workflows::uri as uri_workflow;
use agent_dump_core::output::diagnostics;
use agent_dump_core::output::formats as output_formats;
use agent_dump_core::output::i18n;
use agent_dump_core::output::render;
use agent_dump_core::query;
use agent_dump_core::query::text as query_text;
use std::io::{self, Write};

pub fn shell_command(argv: &[String]) -> String {
    if cfg!(windows) {
        return "& ".to_owned()
            + &argv
                .iter()
                .map(|s| format!("'{}'", s.replace('\'', "''")))
                .collect::<Vec<_>>()
                .join(" ");
    }
    argv.iter()
        .map(|s| {
            if !s.is_empty()
                && s.chars().all(|c| {
                    c.is_ascii_alphanumeric() || "_@%+=:,./-".contains(c)
                })
            {
                s.clone()
            } else {
                format!("'{}'", s.replace('\'', "'\"'\"'"))
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}
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
    Browse,
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
            args.search.as_ref().is_some_and(|s| !s.is_empty()) && !args.browse,
            Mode::List,
            "--search",
        ),
        (args.list, Mode::List, "--list"),
        (args.interactive, Mode::Interactive, "--interactive"),
        (args.browse, Mode::Browse, "--browse"),
        (
            query_uri && !args.collect && !args.browse,
            Mode::List,
            "agents:// query URI",
        ),
    ] {
        if present {
            result.push((mode, label));
        }
    }
    if (!query_uri || args.collect)
        && (args.days.is_some()
            || args.time_field.is_some()
            || args.query.as_ref().is_some_and(|s| !s.is_empty()))
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
                .find_map(|key| {
                    std::env::var(key).ok().filter(|v| !v.is_empty())
                })
                .is_some_and(|v| v.starts_with("zh"))
        },
        |lang| lang == "zh",
    );
    let mut plan_stderr = io::stderr();
    let plan_out: &mut dyn Write =
        if args.emit_prompt || args.json || args.read || args.read_prompt {
            &mut plan_stderr
        } else {
            out
        };
    let mode = mode(&args);
    if args.time_field.is_some()
        && !matches!(mode, Mode::List | Mode::Interactive | Mode::Browse)
    {
        eprintln!("{}", i18n::t("TIME_FIELD_MODE_ERROR", zh, &[]));
        return Ok(false);
    }
    if (args.read || args.read_prompt)
        && (mode != Mode::Uri
            || candidates(&args)
                .iter()
                .any(|(candidate, _)| *candidate != Mode::Uri)
            || args.head
            || args.message.is_some()
            || args.locate
            || args.summary
            || args.format.is_some()
            || args.output.is_some()
            || args.emit_prompt
            || args.dry_run
            || args.since.is_some()
            || args.until.is_some()
            || args.save.is_some()
            || (args.read_prompt && args.json))
    {
        eprintln!("{}", i18n::t("READ_MODE_ERROR", zh, &[]));
        return Ok(false);
    }
    if args.cursor.is_some()
        && (args.limit.is_some()
            || args.max_chars.is_some()
            || args.order.is_some()
            || args.role.is_some()
            || args.read_match.is_some()
            || args.details)
    {
        eprintln!("{}", i18n::t("READ_CURSOR_OPTIONS_ERROR", zh, &[]));
        return Ok(false);
    }
    if args.json
        && !matches!(mode, Mode::List | Mode::Stats | Mode::Providers)
        && !(mode == Mode::Uri
            && (args.message.is_some() || args.read || args.head))
    {
        eprintln!("{}", i18n::t("JSON_MODE_ERROR", zh, &[]));
        return Ok(false);
    }
    if (args.locate
        && (mode != Mode::List
            || args.search.as_deref().is_none_or(str::is_empty)))
        || (args.message.is_some()
            && (mode != Mode::Uri
                || args.head
                || args.summary
                || (args.json
                    && (args.format.is_some() || args.output.is_some()))
                || (args.output.is_some() && args.format.is_none())))
    {
        eprintln!("{}", i18n::t("MESSAGE_MODE_ERROR", zh, &[]));
        return Ok(false);
    }
    let query_uri_requested = args
        .uri
        .as_deref()
        .is_some_and(|s| s.starts_with("agents://"));
    let error_key = if args.emit_prompt && mode != Mode::Collect {
        Some("EMIT_PROMPT_REQUIRES_COLLECT")
    } else if args.emit_prompt && args.dry_run {
        Some("COLLECT_ACTION_CONFLICT")
    } else if mode == Mode::Collect
        && (args.list
            || args.interactive
            || args.browse
            || (args.uri.is_some() && !query_uri_requested))
    {
        Some("COLLECT_MODE_CONFLICT")
    } else if mode == Mode::Uri
        && args.head
        && args.summary
        && args.format.is_none()
    {
        Some("URI_HEAD_WITH_SUMMARY_ERROR")
    } else {
        None
    };
    if let Some(key) = error_key {
        if args.emit_prompt || args.json {
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
        return maintenance::providers(args.json, zh, out);
    }
    if let Some(action) = &args.config {
        return config_command::run(action, zh, out, &mut io::stdin().lock());
    }
    if matches!(
        mode,
        Mode::Collect
            | Mode::Stats
            | Mode::Reindex
            | Mode::List
            | Mode::Interactive
            | Mode::Browse
    ) && let Some(days) = args.days
    {
        let maximum = i64::from(
            jiff::Zoned::now()
                .date()
                .since((jiff::Unit::Day, jiff::civil::date(1, 1, 1)))?
                .get_days(),
        ) + 1;
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
            && matches!(
                mode,
                Mode::Collect | Mode::List | Mode::Interactive | Mode::Browse
            )
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
                !matches!(mode, Mode::Uri | Mode::Reindex)
                    && (mode != Mode::Stats || !q.is_empty())
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
                diagnostics::Diagnostic::query_error(
                    &error.to_string(),
                    query_uri,
                    false,
                    zh
                )
                .render(zh)
            )?;
            return Ok(false);
        }
    };
    if args.time_field.as_deref() == Some("updated") {
        query.get_or_insert_with(query::Query::default).time_field =
            query::TimeField::Updated;
    }
    if mode == Mode::Collect {
        return collect_workflow::run(
            &collect_model::Operation {
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
            query.as_ref(),
            args.days.unwrap_or(7),
            mode == Mode::Reindex,
            args.json,
            zh,
            out,
            &mut io::stderr(),
        );
    }
    if let Some(search) = args
        .search
        .as_ref()
        .filter(|s| !s.is_empty() && matches!(mode, Mode::List | Mode::Browse))
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
                    i18n::t(
                        "CLI_FORMAT_INVALID",
                        zh,
                        &[("value", spec.clone())],
                    ),
                )
            })?;
        }
        return list_workflow::run(
            query.as_ref(),
            args.days.unwrap_or(7),
            &list_workflow::Options {
                summary: !args.no_metadata_summary,
                ignored: (args.format.is_some(), args.output.is_some()),
                json: args.json,
                locate: args.locate,
            },
            zh,
            out,
            &mut io::stderr(),
        );
    }
    if mode == Mode::Browse {
        let formats =
            output_formats::parse(args.format.as_deref().unwrap_or("json"))?;
        if formats.contains(&output_formats::OutputFormat::Print) {
            writeln!(
                out,
                "{}",
                diagnostics::Diagnostic::interactive_print(zh).render(zh)
            )?;
            return Ok(false);
        }
        return crate::workflows::reader::run(
            &crate::workflows::interactive::Operation {
                query,
                days: args.days.unwrap_or(7),
                formats,
                output: args.output,
                metadata: !args.no_metadata_summary,
            },
            zh,
            out,
            &mut io::stderr(),
        );
    }
    if mode == Mode::Interactive {
        let formats =
            output_formats::parse(args.format.as_deref().unwrap_or("json"))?;
        if formats.contains(&output_formats::OutputFormat::Print) {
            write!(
                out,
                "{}",
                diagnostics::Diagnostic::interactive_print(zh).render(zh)
            )?;
            return Ok(false);
        }
        return crate::workflows::interactive::run(
            &crate::workflows::interactive::Operation {
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
            plan_out,
            "{}",
            if zh {
                "❌ --head 不能与 -format/--format 同时使用。"
            } else {
                "❌ --head cannot be used with -format/--format."
            }
        )?;
        return Ok(false);
    }
    let formats = if args.head || args.read || args.read_prompt {
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
    if args.message.is_some()
        && args.format.is_some()
        && formats.iter().any(|format| {
            !matches!(
                format,
                output_formats::OutputFormat::Json
                    | output_formats::OutputFormat::Markdown
            )
        })
    {
        eprintln!("{}", i18n::t("MESSAGE_EXPORT_FORMAT_ERROR", zh, &[]));
        return Ok(false);
    }
    uri_workflow::run(
        &uri_workflow::UriOperation {
            uri,
            head: args.head,
            summary: args.summary,
            message: args.message,
            before: args.before.unwrap_or(3) as usize,
            after: args.after.unwrap_or(3) as usize,
            json: args.json,
            read: if args.read_prompt {
                Some(uri_workflow::ReadOperation::Prompt)
            } else {
                args.read.then(|| {
                    use agent_dump_core::query::read::{
                        Options, Order, Request,
                    };
                    uri_workflow::ReadOperation::Page(
                        if let Some(cursor) = args.cursor {
                            Request::Continue(cursor)
                        } else {
                            let defaults = Options::default();
                            Request::Start(Options {
                                limit: args.limit.unwrap_or(defaults.limit),
                                max_chars: args
                                    .max_chars
                                    .unwrap_or(defaults.max_chars),
                                order: if args.order.as_deref() == Some("asc") {
                                    Order::Asc
                                } else {
                                    Order::Desc
                                },
                                role: args
                                    .role
                                    .map(|s| s.trim().to_lowercase()),
                                keyword: args.read_match,
                                details: args.details,
                            })
                        },
                    )
                })
            },
            formats,
            output: args.output,
        },
        zh,
        out,
        &mut io::stderr(),
    )
}
