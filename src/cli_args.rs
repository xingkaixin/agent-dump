use crate::collect_model;
use clap::{CommandFactory, FromArgMatches, Parser};
use std::ffi::OsString;
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "agent-dump",
    version,
    args_override_self = true,
    infer_long_args = true
)]
pub struct Args {
    pub uri: Option<String>,
    #[arg(long)]
    pub list: bool,
    #[arg(long)]
    pub search: Option<String>,
    #[arg(long)]
    pub stats: bool,
    #[arg(long, alias = "capabilities")]
    pub providers: bool,
    #[arg(long, value_parser = ["view", "edit"])]
    pub config: Option<String>,
    #[arg(long)]
    pub reindex: bool,
    #[arg(long)]
    pub collect: bool,
    #[arg(long, value_enum, default_value = "pm")]
    pub collect_mode: collect_model::Mode,
    #[arg(long)]
    pub dry_run: bool,
    #[arg(long)]
    pub emit_prompt: bool,
    #[arg(long)]
    pub since: Option<String>,
    #[arg(long)]
    pub until: Option<String>,
    #[arg(long)]
    pub save: Option<String>,
    #[arg(long)]
    pub summary: bool,
    #[arg(short = 'i', long)]
    pub interactive: bool,
    #[arg(long)]
    pub head: bool,
    #[arg(short = 'd', long = "days", allow_hyphen_values = true)]
    pub days: Option<i64>,
    #[arg(short = 'q', long = "query")]
    pub query: Option<String>,
    #[arg(long)]
    pub no_metadata_summary: bool,
    #[arg(short = 'p', long, default_value_t = 20)]
    pub page_size: i64,
    #[arg(long)]
    pub format: Option<String>,
    #[arg(long)]
    pub output: Option<PathBuf>,
    #[arg(long, value_parser = ["en", "zh"])]
    pub lang: Option<String>,
}

pub fn normalize_arguments(args: Vec<OsString>) -> Vec<OsString> {
    let mut positional = false;
    let mut expects_value = false;
    args.into_iter()
        .enumerate()
        .map(|(index, arg)| {
            if index == 0 || positional {
                return arg;
            }
            if expects_value {
                expects_value = false;
                return arg;
            }
            if arg == "--" {
                positional = true;
                return arg;
            }
            let value = arg.to_string_lossy();
            let (name, equals) = value
                .split_once('=')
                .map_or((value.as_ref(), None), |(k, v)| (k, Some(v)));
            let normalized = match name {
                "-days" => "--days",
                "-query" => "--query",
                "-format" => "--format",
                "-output" => "--output",
                "-v" => "--version",
                "-config" => "--config",
                "-summary" => "--summary",
                "-since" => "--since",
                "-until" => "--until",
                "-page-size" => "--page-size",
                _ => name,
            };
            expects_value = equals.is_none()
                && matches!(
                    normalized,
                    "-d" | "--days"
                        | "-q"
                        | "--query"
                        | "--format"
                        | "--output"
                        | "--lang"
                        | "--search"
                        | "--config"
                        | "--collect-mode"
                        | "--since"
                        | "--until"
                        | "--save"
                        | "-p"
                        | "--page-size"
                );
            if let Some(value) = equals {
                format!("{normalized}={value}").into()
            } else {
                OsString::from(normalized)
            }
        })
        .collect()
}

pub fn command(zh: bool) -> clap::Command {
    let mut command = Args::command()
        .about(crate::i18n::t("CLI_DESC", zh, &[]))
        .disable_version_flag(true)
        .arg(
            clap::Arg::new("version")
                .long("version")
                .action(clap::ArgAction::Version),
        );
    command = command.arg(
        clap::Arg::new("shortcut")
            .long("shortcut")
            .value_name("SHORTCUT"),
    );
    for (id, key) in [
        ("uri", "URI"),
        ("days", "DAYS"),
        ("output", "OUTPUT"),
        ("format", "FORMAT"),
        ("head", "HEAD"),
        ("summary", "SUMMARY"),
        ("collect", "COLLECT"),
        ("collect_mode", "COLLECT_MODE"),
        ("dry_run", "DRY_RUN"),
        ("emit_prompt", "EMIT_PROMPT"),
        ("stats", "STATS"),
        ("providers", "PROVIDERS"),
        ("shortcut", "SHORTCUT"),
        ("since", "SINCE"),
        ("until", "UNTIL"),
        ("save", "SAVE"),
        ("config", "CONFIG"),
        ("list", "LIST"),
        ("interactive", "INTERACTIVE"),
        ("no_metadata_summary", "NO_METADATA_SUMMARY"),
        ("page_size", "PAGE_SIZE"),
        ("query", "QUERY"),
        ("search", "SEARCH"),
        ("reindex", "REINDEX"),
        ("lang", "LANG"),
        ("version", "VERSION"),
    ] {
        command = command.mut_arg(id, |arg| {
            arg.help(crate::i18n::t(&format!("CLI_{key}_HELP"), zh, &[]))
        });
    }
    command.after_help(if zh {
        "兼容别名：-days、-output、-format、-summary、-since、-until、-config、-page-size、-query、-v；--capabilities 等同于 --providers。"
    } else {
        "Compatibility aliases: -days, -output, -format, -summary, -since, -until, -config, -page-size, -query, -v; --capabilities is an alias for --providers."
    })
}

pub fn parse(arguments: Vec<OsString>, zh: bool) -> std::result::Result<Args, clap::Error> {
    let matches = command(zh).try_get_matches_from(arguments)?;
    Args::from_arg_matches(&matches)
}

pub fn language(arguments: &[OsString]) -> bool {
    let explicit = arguments
        .iter()
        .enumerate()
        .filter_map(|(index, argument)| {
            if argument == "--lang" {
                arguments
                    .get(index + 1)
                    .map(|value| value.to_string_lossy().into_owned())
            } else {
                argument
                    .to_str()
                    .and_then(|value| value.strip_prefix("--lang="))
                    .map(str::to_owned)
            }
        })
        .next_back();
    explicit.map_or_else(
        || {
            ["LC_ALL", "LC_MESSAGES", "LANG"]
                .iter()
                .find_map(|key| std::env::var(key).ok().filter(|value| !value.is_empty()))
                .is_some_and(|value| value.to_lowercase().starts_with("zh"))
        },
        |value| value == "zh",
    )
}
