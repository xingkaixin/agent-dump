use crate::collect_model;
use clap::Parser;
use std::ffi::OsString;
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "agent-dump",
    version,
    about = "Experimental Rust: session discovery, search and export",
    after_help = "Python remains the default CLI. Rust supports ten Providers, Query/Search, statistics, index maintenance and single-session export. Collect, configuration and shortcuts are also available. Python remains the default installation.",
    arg_required_else_help = true
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
