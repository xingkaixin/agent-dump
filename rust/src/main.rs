mod cherry;
mod claude;
mod claude_transcript;
mod codex;
mod codex_enrichment;
mod codex_patch;
mod codex_transcript;
mod cursor;
mod cursor_transcript;
mod deepchat;
mod desktop;
mod diagnostics;
mod export;
mod file_sessions;
mod jsonl;
mod kimi;
mod kimi_transcript;
mod kimi_wire;
mod list_workflow;
mod message_assembly;
mod minimax;
mod opencode_v2;
mod output_formats;
mod pi;
mod pi_transcript;
mod provider;
mod provider_error;
mod python_json;
mod registry;
mod render;
mod session;
mod session_data;
#[cfg(test)]
mod source_tests;
mod sqlite;
mod sqlite_legacy;
mod sqlite_provider;
mod timestamp;
mod title;
mod uri_workflow;
mod value;

use clap::Parser;
use std::ffi::OsString;
use std::io::{self, Write};
use std::path::PathBuf;

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

#[derive(Parser)]
#[command(
    name = "agent-dump",
    version,
    about = "Experimental Rust: session discovery and export",
    after_help = "Python remains the default CLI. Rust supports ten Providers for listing and single-session export. Search, collect, configuration, batch export and TUI are not implemented yet.",
    arg_required_else_help = true
)]
struct Args {
    uri: Option<String>,
    #[arg(long, conflicts_with = "uri")]
    list: bool,
    #[arg(long, requires = "uri")]
    head: bool,
    #[arg(short = 'd', long = "days", default_value_t = 7, value_parser = clap::value_parser!(i64).range(1..))]
    days: i64,
    #[arg(short = 'q', long = "query", requires = "list")]
    query: Option<String>,
    #[arg(long, requires = "list")]
    no_metadata_summary: bool,
    #[arg(long, requires = "uri")]
    format: Option<String>,
    #[arg(long, requires = "uri")]
    output: Option<PathBuf>,
    #[arg(long, value_parser = ["en", "zh"])]
    lang: Option<String>,
}

fn arguments() -> Vec<OsString> {
    let mut positional = false;
    let mut expects_value = false;
    std::env::args_os()
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
                _ => name,
            };
            expects_value = equals.is_none()
                && matches!(
                    normalized,
                    "-d" | "--days" | "-q" | "--query" | "--format" | "--output" | "--lang"
                );
            if let Some(value) = equals {
                format!("{normalized}={value}").into()
            } else {
                OsString::from(normalized)
            }
        })
        .collect()
}

fn run(args: Args, out: &mut impl Write) -> Result<bool> {
    let zh = args.lang.as_deref().map_or_else(
        || {
            ["LC_ALL", "LC_MESSAGES", "LANG"]
                .iter()
                .find_map(|key| std::env::var(key).ok().filter(|v| !v.is_empty()))
                .is_some_and(|v| v.starts_with("zh"))
        },
        |lang| lang == "zh",
    );
    if args.list {
        return list_workflow::run(
            args.query.as_deref(),
            args.days,
            !args.no_metadata_summary,
            zh,
            out,
            &mut io::stderr().lock(),
        );
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
            formats,
            output: args.output,
        },
        zh,
        out,
        &mut io::stderr().lock(),
    )
}

fn main() -> std::process::ExitCode {
    let args = Args::parse_from(arguments());
    let mut out = io::BufWriter::new(io::stdout().lock());
    match run(args, &mut out).and_then(|success| {
        out.flush()?;
        Ok(success)
    }) {
        Ok(true) => std::process::ExitCode::SUCCESS,
        Ok(false) => std::process::ExitCode::FAILURE,
        Err(error) => {
            if let Some(error) = error.downcast_ref::<clap::Error>() {
                let _ = error.print();
                return std::process::ExitCode::from(error.exit_code() as u8);
            }
            if error
                .downcast_ref::<io::Error>()
                .is_some_and(|e| e.kind() == io::ErrorKind::BrokenPipe)
            {
                return std::process::ExitCode::SUCCESS;
            }
            eprintln!("Error: {}", render::safe_line(&error.to_string()));
            std::process::ExitCode::FAILURE
        }
    }
}
