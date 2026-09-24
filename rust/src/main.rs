mod codex;
mod codex_transcript;
mod export;
mod jsonl;
mod render;
mod session;

use clap::Parser;
use std::ffi::OsString;
use std::io::{self, Write};
use std::path::PathBuf;

pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Parser)]
#[command(
    name = "agent-dump",
    version,
    about = "Experimental Rust P1: Codex discovery and text session export",
    after_help = "Python remains the default CLI. Search, collect, configuration, TUI and complex Codex messages are not implemented yet.",
    arg_required_else_help = true
)]
struct Args {
    uri: Option<String>,
    #[arg(long, conflicts_with = "uri")]
    list: bool,
    #[arg(long, requires = "uri", conflicts_with_all = ["format", "output"])]
    head: bool,
    #[arg(short = 'd', long = "days", default_value_t = 7, value_parser = clap::value_parser!(i64).range(1..))]
    days: i64,
    #[arg(short = 'q', long = "query", requires = "list")]
    query: Option<String>,
    #[arg(long, requires = "list")]
    no_metadata_summary: bool,
    #[arg(long, requires = "uri")]
    format: Option<String>,
    #[arg(long, requires = "format")]
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

fn run(args: Args, out: &mut impl Write) -> Result<()> {
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
        if args.query.as_deref() != Some("provider:codex") {
            return Err("Rust P1 list requires -q provider:codex; other Providers and queries are not implemented yet".into());
        }
        let provider = codex::Codex::open()?;
        let sessions = provider.discover(args.days)?;
        write!(
            out,
            "{}",
            render::list(&sessions, args.days, !args.no_metadata_summary, zh)
        )?;
        return Ok(());
    }
    let uri = args.uri.ok_or("Provide a Codex URI or --list")?;
    let id = uri
        .strip_prefix("codex://")
        .ok_or("Rust P1 only supports codex:// URIs")?;
    let id = id.strip_prefix("threads/").unwrap_or(id);
    if id.is_empty() {
        return Err("Empty Codex session id".into());
    }
    let formats: Vec<_> = args
        .format
        .as_deref()
        .unwrap_or("print")
        .split(',')
        .map(|v| v.trim().to_lowercase())
        .collect();
    if formats.iter().any(|v| v != "print" && v != "json") {
        return Err("Rust P1 supports only print and json formats".into());
    }
    if formats.iter().any(|v| v == "json") && args.output.is_none() {
        return Err(
            "Rust P1 JSON export requires --output; configuration defaults are not implemented yet"
                .into(),
        );
    }
    let provider = codex::Codex::open()?;
    let session = provider.find(id)?;
    if args.head {
        write!(out, "{}", render::head(&uri, &session, zh))?;
        return Ok(());
    }
    let mut data = provider.read(&session)?;
    if formats.iter().any(|v| v == "print") {
        writeln!(out, "{}", render::transcript(&uri, &data))?;
    }
    if formats.iter().any(|v| v == "json") {
        let path = export::json(
            &mut data,
            args.output.as_deref().unwrap(),
            provider.source_root(),
        )?;
        let path = render::safe_line(&path.display().to_string());
        writeln!(
            out,
            "{}",
            if zh {
                format!("✅ 已导出 [json] 到: {path}")
            } else {
                format!("✅ Exported session [json] to: {path}")
            }
        )?;
    }
    Ok(())
}

fn main() -> std::process::ExitCode {
    let args = Args::parse_from(arguments());
    let mut out = io::BufWriter::new(io::stdout().lock());
    match run(args, &mut out).and_then(|()| {
        out.flush()?;
        Ok(())
    }) {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
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
