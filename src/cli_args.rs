use crate::collect::model as collect_model;
use agent_dump_core::output::i18n::t;
use clap::{CommandFactory, FromArgMatches, Parser};
use std::ffi::OsString;
use std::fmt::Write as _;
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "agent-dump",
    version,
    args_override_self = true,
    infer_long_args = true
)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "Independent CLI flags are validated together by command planning"
)]
pub struct Args {
    pub uri: Option<String>,
    #[arg(long)]
    pub list: bool,
    #[arg(long)]
    pub json: bool,
    #[arg(long, conflicts_with = "read_prompt")]
    pub read: bool,
    #[arg(long)]
    pub read_prompt: bool,
    #[arg(long, requires = "read", value_parser = clap::value_parser!(u32).range(1..=100))]
    pub limit: Option<u32>,
    #[arg(long, requires = "read")]
    pub cursor: Option<String>,
    #[arg(long, requires = "read", value_parser = ["asc", "desc"])]
    pub order: Option<String>,
    #[arg(long, requires = "read")]
    pub role: Option<String>,
    #[arg(long = "match", requires = "read")]
    pub read_match: Option<String>,
    #[arg(long, requires = "read", value_parser = clap::value_parser!(u32).range(1..=100_000))]
    pub max_chars: Option<u32>,
    #[arg(long, requires = "read")]
    pub details: bool,
    #[arg(long)]
    pub locate: bool,
    #[arg(long)]
    pub message: Option<String>,
    #[arg(long, requires = "message")]
    pub before: Option<u32>,
    #[arg(long, requires = "message")]
    pub after: Option<u32>,
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
    #[arg(long, value_name = "FILE")]
    pub verify_manifest: Option<PathBuf>,
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
    pub browse: bool,
    #[arg(long)]
    pub head: bool,
    #[arg(short = 'd', long = "days", allow_hyphen_values = true)]
    pub days: Option<i64>,
    #[arg(long, value_parser = ["created", "updated"])]
    pub time_field: Option<String>,
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

const SUBCOMMANDS: [(&str, &str); 13] = [
    ("list", "--list"),
    ("search", "--search"),
    ("browse", "--browse"),
    ("export", ""),
    ("head", "--head"),
    ("read", "--read"),
    ("read-prompt", "--read-prompt"),
    ("collect", "--collect"),
    ("stats", "--stats"),
    ("providers", "--providers"),
    ("config", "--config"),
    ("reindex", "--reindex"),
    ("shortcut", "--shortcut"),
];

struct SubcommandHelp {
    name: &'static str,
    usage: &'static str,
    desc_key: &'static str,
    options: &'static [(&'static str, &'static str)],
    notes_key: &'static str,
    examples: &'static [&'static str],
}

const SUBCOMMAND_HELP: &[SubcommandHelp] = &[
    SubcommandHelp {
        name: "list",
        usage: "agent-dump list [QUERY_URI] [OPTIONS]",
        desc_key: "CLI_SUBCMD_LIST_DESC",
        options: &[
            ("-d, --days <DAYS>", "CLI_DAYS_HELP"),
            ("--time-field <FIELD>", "CLI_TIME_FIELD_HELP"),
            ("-q, --query <QUERY>", "CLI_QUERY_HELP"),
            ("--json", "CLI_JSON_HELP"),
            ("--no-metadata-summary", "CLI_NO_METADATA_SUMMARY_HELP"),
        ],
        notes_key: "CLI_SUBCMD_LIST_NOTES",
        examples: &[
            "agent-dump list -d 7 --json",
            "agent-dump list -q \"provider:codex path:.\"",
        ],
    },
    SubcommandHelp {
        name: "search",
        usage: "agent-dump search <TERMS> [QUERY_URI] [OPTIONS]",
        desc_key: "CLI_SUBCMD_SEARCH_DESC",
        options: &[
            ("-d, --days <DAYS>", "CLI_DAYS_HELP"),
            ("--time-field <FIELD>", "CLI_TIME_FIELD_HELP"),
            ("-q, --query <QUERY>", "CLI_QUERY_HELP"),
            ("--locate", "CLI_LOCATE_HELP"),
            ("--json", "CLI_JSON_HELP"),
            ("--no-metadata-summary", "CLI_NO_METADATA_SUMMARY_HELP"),
        ],
        notes_key: "CLI_SUBCMD_SEARCH_NOTES",
        examples: &[
            "agent-dump search \"auth token\" -d 30 --json",
            "agent-dump search \"panic\" --locate -q \"provider:codex\"",
        ],
    },
    SubcommandHelp {
        name: "browse",
        usage: "agent-dump browse [QUERY_URI] [OPTIONS]",
        desc_key: "CLI_SUBCMD_BROWSE_DESC",
        options: &[
            ("-d, --days <DAYS>", "CLI_DAYS_HELP"),
            ("--time-field <FIELD>", "CLI_TIME_FIELD_HELP"),
            ("-q, --query <QUERY>", "CLI_QUERY_HELP"),
            ("--search <TERMS>", "CLI_SEARCH_HELP"),
            ("--format <FORMAT>", "CLI_FORMAT_HELP"),
            ("--output <DIR>", "CLI_OUTPUT_HELP"),
            ("--no-metadata-summary", "CLI_NO_METADATA_SUMMARY_HELP"),
        ],
        notes_key: "CLI_SUBCMD_BROWSE_NOTES",
        examples: &[
            "agent-dump browse -d 14",
            "agent-dump browse -q \"provider:claude\" --output ./exports",
        ],
    },
    SubcommandHelp {
        name: "export",
        usage: "agent-dump export [URI] [OPTIONS]",
        desc_key: "CLI_SUBCMD_EXPORT_DESC",
        options: &[
            ("--format <FORMAT>", "CLI_FORMAT_HELP"),
            ("--output <DIR>", "CLI_OUTPUT_HELP"),
            ("--summary", "CLI_SUMMARY_HELP"),
            ("--message <LOCATOR>", "CLI_MESSAGE_HELP"),
            ("--before <N>", "CLI_BEFORE_HELP"),
            ("--after <N>", "CLI_AFTER_HELP"),
            ("-d, --days <DAYS>", "CLI_DAYS_HELP"),
            ("--time-field <FIELD>", "CLI_TIME_FIELD_HELP"),
            ("-q, --query <QUERY>", "CLI_QUERY_HELP"),
            ("--no-metadata-summary", "CLI_NO_METADATA_SUMMARY_HELP"),
        ],
        notes_key: "CLI_SUBCMD_EXPORT_NOTES",
        examples: &[
            "agent-dump export codex://<id> --format markdown --output ./exports",
            "agent-dump codex://<id> --message <LOCATOR> --json",
            "agent-dump export -d 7 --format json,markdown",
        ],
    },
    SubcommandHelp {
        name: "head",
        usage: "agent-dump head <URI> [OPTIONS]",
        desc_key: "CLI_SUBCMD_HEAD_DESC",
        options: &[("--json", "CLI_JSON_HELP")],
        notes_key: "CLI_SUBCMD_HEAD_NOTES",
        examples: &[
            "agent-dump head codex://<id>",
            "agent-dump head codex://<id> --json",
        ],
    },
    SubcommandHelp {
        name: "read",
        usage: "agent-dump read <URI> [OPTIONS]",
        desc_key: "CLI_SUBCMD_READ_DESC",
        options: &[
            ("--limit <1..100>", "CLI_READ_LIMIT_HELP"),
            ("--max-chars <1..100000>", "CLI_READ_MAX_CHARS_HELP"),
            ("--order <asc|desc>", "CLI_READ_ORDER_HELP"),
            ("--role <ROLE>", "CLI_READ_ROLE_HELP"),
            ("--match <PHRASE>", "CLI_READ_MATCH_HELP"),
            ("--details", "CLI_READ_DETAILS_HELP"),
            ("--cursor <CURSOR>", "CLI_READ_CURSOR_HELP"),
            ("--json", "CLI_JSON_HELP"),
        ],
        notes_key: "CLI_SUBCMD_READ_NOTES",
        examples: &[
            "agent-dump read codex://<id> --limit 10 --json",
            "agent-dump read codex://<id> --cursor <CURSOR> --json",
        ],
    },
    SubcommandHelp {
        name: "read-prompt",
        usage: "agent-dump read-prompt <URI> [OPTIONS]",
        desc_key: "CLI_SUBCMD_READ_PROMPT_DESC",
        options: &[],
        notes_key: "CLI_SUBCMD_READ_PROMPT_NOTES",
        examples: &[
            "agent-dump read-prompt codex://<id>",
            "agent-dump read-prompt claude://<id> --lang zh",
        ],
    },
    SubcommandHelp {
        name: "collect",
        usage: "agent-dump collect [QUERY_URI] [OPTIONS]",
        desc_key: "CLI_SUBCMD_COLLECT_DESC",
        options: &[
            ("-d, --days <DAYS>", "CLI_DAYS_HELP"),
            ("--since <DATE>", "CLI_SINCE_HELP"),
            ("--until <DATE>", "CLI_UNTIL_HELP"),
            ("--collect-mode <MODE>", "CLI_COLLECT_MODE_HELP"),
            ("-q, --query <QUERY>", "CLI_QUERY_HELP"),
            ("--save <PATH>", "CLI_SAVE_HELP"),
            ("--dry-run", "CLI_DRY_RUN_HELP"),
            ("--emit-prompt", "CLI_EMIT_PROMPT_HELP"),
            ("--output <PATH>", "CLI_OUTPUT_HELP"),
            ("--verify-manifest <FILE>", "CLI_VERIFY_MANIFEST_HELP"),
            ("--json", "CLI_JSON_HELP"),
        ],
        notes_key: "CLI_SUBCMD_COLLECT_NOTES",
        examples: &[
            "agent-dump collect --since 2026-01-01 --until 2026-01-07 --dry-run",
            "agent-dump collect --since 2026-01-01 --emit-prompt --output ./prompt.txt",
        ],
    },
    SubcommandHelp {
        name: "stats",
        usage: "agent-dump stats [OPTIONS]",
        desc_key: "CLI_SUBCMD_STATS_DESC",
        options: &[
            ("-d, --days <DAYS>", "CLI_DAYS_HELP"),
            ("-q, --query <QUERY>", "CLI_QUERY_HELP"),
            ("--json", "CLI_JSON_HELP"),
        ],
        notes_key: "CLI_SUBCMD_STATS_NOTES",
        examples: &[
            "agent-dump stats -d 30",
            "agent-dump stats -d 30 -q \"provider:codex\" --json",
        ],
    },
    SubcommandHelp {
        name: "providers",
        usage: "agent-dump providers [OPTIONS]",
        desc_key: "CLI_SUBCMD_PROVIDERS_DESC",
        options: &[("--json", "CLI_JSON_HELP")],
        notes_key: "CLI_SUBCMD_PROVIDERS_NOTES",
        examples: &["agent-dump providers", "agent-dump providers --json"],
    },
    SubcommandHelp {
        name: "config",
        usage: "agent-dump config <view|edit> [OPTIONS]",
        desc_key: "CLI_SUBCMD_CONFIG_DESC",
        options: &[],
        notes_key: "CLI_SUBCMD_CONFIG_NOTES",
        examples: &["agent-dump config view", "agent-dump config edit"],
    },
    SubcommandHelp {
        name: "reindex",
        usage: "agent-dump reindex [OPTIONS]",
        desc_key: "CLI_SUBCMD_REINDEX_DESC",
        options: &[("-d, --days <DAYS>", "CLI_DAYS_HELP")],
        notes_key: "CLI_SUBCMD_REINDEX_NOTES",
        examples: &["agent-dump reindex", "agent-dump reindex -d 90"],
    },
    SubcommandHelp {
        name: "shortcut",
        usage: "agent-dump shortcut <NAME> [ARGS...] [OPTIONS]",
        desc_key: "CLI_SUBCMD_SHORTCUT_DESC",
        options: &[],
        notes_key: "CLI_SUBCMD_SHORTCUT_NOTES",
        examples: &[
            "agent-dump shortcut daily 2026-01-15",
            "agent-dump shortcut weekly --dry-run",
        ],
    },
];

pub fn subcommand_help(arguments: &[OsString]) -> Option<String> {
    let name = arguments.get(1)?.to_str()?;
    let spec = SUBCOMMAND_HELP.iter().find(|spec| spec.name == name)?;
    let requested = arguments[2..]
        .iter()
        .take_while(|arg| *arg != "--")
        .any(|arg| arg == "-h" || arg == "--help");
    if !requested {
        return None;
    }
    Some(render_subcommand_help(spec, language(arguments)))
}

fn render_subcommand_help(spec: &SubcommandHelp, zh: bool) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "{}\n", t(spec.desc_key, zh, &[]));
    let _ = writeln!(
        out,
        "{}\n  {}\n",
        if zh { "用法:" } else { "Usage:" },
        spec.usage
    );
    let mut options: Vec<(&str, &str)> = spec.options.to_vec();
    options.push(("--lang <en|zh>", "CLI_LANG_HELP"));
    options.push(("-h, --help", "CLI_HELP_HELP"));
    let width = options
        .iter()
        .map(|(flag, _)| flag.len())
        .max()
        .unwrap_or(0);
    let _ = writeln!(out, "{}", if zh { "选项:" } else { "Options:" });
    for (flag, key) in options {
        let _ = writeln!(out, "  {flag:<width$}  {}", t(key, zh, &[]));
    }
    let notes = t(spec.notes_key, zh, &[]);
    if !notes.is_empty() {
        let _ = writeln!(out, "\n{}", if zh { "说明:" } else { "Notes:" });
        for line in notes.lines() {
            let _ = writeln!(out, "  - {line}");
        }
    }
    if !spec.examples.is_empty() {
        let _ = writeln!(out, "\n{}", if zh { "示例:" } else { "Examples:" });
        for example in spec.examples {
            let _ = writeln!(out, "  {example}");
        }
    }
    out
}

fn expand_subcommand(mut args: Vec<OsString>) -> Vec<OsString> {
    let Some((name, flag)) = args.get(1).and_then(|arg| {
        SUBCOMMANDS.iter().find(|(name, _)| arg == *name).copied()
    }) else {
        return args;
    };
    if name != "export" {
        args[1] = flag.into();
        return args;
    }
    args.remove(1);
    let uri = args.iter().skip(1).any(|arg| {
        let arg = arg.to_string_lossy();
        arg.contains("://") && !arg.starts_with("agents://")
    });
    let format = args.iter().any(|arg| {
        let arg = arg.to_string_lossy();
        ["--format", "-format"]
            .iter()
            .any(|flag| arg == *flag || arg.starts_with(&format!("{flag}=")))
    });
    if !uri {
        args.insert(1, "--interactive".into());
    } else if !format {
        args.extend(["--format".into(), "json".into()]);
    }
    args
}

pub fn normalize_arguments(args: Vec<OsString>) -> Vec<OsString> {
    let args = expand_subcommand(args);
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
                .map_or_else(|| (value.as_ref(), None), |(k, v)| (k, Some(v)));
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
                        | "--time-field"
                        | "-q"
                        | "--query"
                        | "--format"
                        | "--output"
                        | "--lang"
                        | "--search"
                        | "--message"
                        | "--before"
                        | "--after"
                        | "--limit"
                        | "--cursor"
                        | "--order"
                        | "--role"
                        | "--match"
                        | "--max-chars"
                        | "--config"
                        | "--collect-mode"
                        | "--since"
                        | "--until"
                        | "--save"
                        | "--verify-manifest"
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
        .about(t("CLI_DESC", zh, &[]))
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
        ("time_field", "TIME_FIELD"),
        ("output", "OUTPUT"),
        ("format", "FORMAT"),
        ("head", "HEAD"),
        ("summary", "SUMMARY"),
        ("collect", "COLLECT"),
        ("collect_mode", "COLLECT_MODE"),
        ("dry_run", "DRY_RUN"),
        ("emit_prompt", "EMIT_PROMPT"),
        ("verify_manifest", "VERIFY_MANIFEST"),
        ("stats", "STATS"),
        ("providers", "PROVIDERS"),
        ("shortcut", "SHORTCUT"),
        ("since", "SINCE"),
        ("until", "UNTIL"),
        ("save", "SAVE"),
        ("config", "CONFIG"),
        ("list", "LIST"),
        ("json", "JSON"),
        ("read", "READ"),
        ("read_prompt", "READ_PROMPT"),
        ("limit", "READ_LIMIT"),
        ("cursor", "READ_CURSOR"),
        ("order", "READ_ORDER"),
        ("role", "READ_ROLE"),
        ("read_match", "READ_MATCH"),
        ("max_chars", "READ_MAX_CHARS"),
        ("details", "READ_DETAILS"),
        ("locate", "LOCATE"),
        ("message", "MESSAGE"),
        ("before", "BEFORE"),
        ("after", "AFTER"),
        ("interactive", "INTERACTIVE"),
        ("browse", "BROWSE"),
        ("no_metadata_summary", "NO_METADATA_SUMMARY"),
        ("page_size", "PAGE_SIZE"),
        ("query", "QUERY"),
        ("search", "SEARCH"),
        ("reindex", "REINDEX"),
        ("lang", "LANG"),
        ("version", "VERSION"),
    ] {
        command = command.mut_arg(id, |arg| {
            arg.help(t(&format!("CLI_{key}_HELP"), zh, &[]))
        });
    }
    command.after_help(if zh {
        "命令（等同于对应参数，参数写法继续可用）：
  list                    --list
  search <TERMS>          --search <TERMS>
  browse                  --browse
  export [URI]            URI 默认 --format json；无 URI 时为 --interactive
  head <URI>              <URI> --head
  read <URI>              <URI> --read
  read-prompt <URI>       <URI> --read-prompt
  collect                 --collect
  stats                   --stats
  providers               --providers
  config <view|edit>      --config <view|edit>
  reindex                 --reindex
  shortcut <NAME> [ARGS]  --shortcut <NAME> [ARGS]

兼容别名：-days、-output、-format、-summary、-since、-until、-config、\
-page-size、-query、-v；--capabilities 等同于 --providers。"
    } else {
        "Commands (equivalent to the listed options, which remain available):
  list                    --list
  search <TERMS>          --search <TERMS>
  browse                  --browse
  export [URI]            URI defaults to --format json; --interactive without a URI
  head <URI>              <URI> --head
  read <URI>              <URI> --read
  read-prompt <URI>       <URI> --read-prompt
  collect                 --collect
  stats                   --stats
  providers               --providers
  config <view|edit>      --config <view|edit>
  reindex                 --reindex
  shortcut <NAME> [ARGS]  --shortcut <NAME> [ARGS]

Compatibility aliases: -days, -output, -format, -summary, -since, -until, \
-config, -page-size, -query, -v; --capabilities is an alias for --providers."
    })
}

pub fn parse(
    arguments: Vec<OsString>,
    zh: bool,
) -> std::result::Result<Args, clap::Error> {
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
                .find_map(|key| {
                    std::env::var(key).ok().filter(|value| !value.is_empty())
                })
                .is_some_and(|value| value.to_lowercase().starts_with("zh"))
        },
        |value| value == "zh",
    )
}
