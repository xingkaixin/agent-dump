mod cherry;
mod claude;
mod claude_transcript;
mod cli_args;
mod codex;
mod codex_enrichment;
mod codex_patch;
mod codex_transcript;
mod collect_events;
mod collect_handoff;
mod collect_log;
mod collect_model;
mod collect_progress;
mod collect_prompts;
mod collect_reduction;
mod collect_sessions;
mod collect_summary;
mod collect_workflow;
mod command;
mod config;
mod config_command;
mod cursor;
mod cursor_transcript;
mod date_input;
mod deepchat;
mod desktop;
mod diagnostics;
mod export;
mod file_sessions;
mod i18n;
mod interactive_workflow;
mod jsonl;
mod kimi;
mod kimi_transcript;
mod kimi_wire;
mod list_workflow;
mod llm;
mod maintenance;
mod message_assembly;
mod minimax;
mod opencode_v2;
mod output_formats;
mod pi;
mod pi_transcript;
mod private_files;
mod provider;
mod provider_error;
mod python_json;
mod query;
mod query_filter;
mod query_text;
mod registry;
mod render;
mod scanner;
mod search_index;
mod selector;
mod session;
mod session_data;
mod shortcut;
mod source_io;
#[cfg(test)]
mod source_tests;
mod sqlite;
mod sqlite_legacy;
mod sqlite_provider;
mod timestamp;
mod title;
mod transcript;
mod tui;
mod uri_workflow;
mod value;

use clap::Parser;
use cli_args::{Args, normalize_arguments};
use std::io::{self, Write};

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;

fn main() -> std::process::ExitCode {
    let arguments = normalize_arguments(std::env::args_os().collect());
    let emit = arguments.iter().any(|arg| arg == "--emit-prompt");
    let zh = arguments
        .windows(2)
        .rev()
        .find(|pair| pair[0] == "--lang")
        .map_or_else(
            || {
                ["LC_ALL", "LC_MESSAGES", "LANG"]
                    .iter()
                    .find_map(|key| std::env::var(key).ok().filter(|s| !s.is_empty()))
                    .is_some_and(|s| s.to_lowercase().contains("zh"))
            },
            |pair| pair[1] == "zh",
        );
    let arguments = match shortcut::expand(arguments, zh) {
        Ok(args) => args,
        Err(error) => {
            if emit {
                eprintln!("{error}");
            } else {
                println!("{error}");
            }
            return std::process::ExitCode::FAILURE;
        }
    };
    let args = Args::parse_from(normalize_arguments(arguments));
    let emit = args.emit_prompt;
    let zh = args.lang.as_deref().map_or(zh, |lang| lang == "zh");
    let mut out = io::BufWriter::new(io::stdout().lock());
    match command::run(args, &mut out).and_then(|success| {
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
            let diagnostic = diagnostics::Diagnostic::unexpected(error.as_ref(), zh).render(zh);
            if emit {
                eprint!("{diagnostic}");
            } else {
                let _ = write!(out, "{diagnostic}");
                let _ = out.flush();
            }
            std::process::ExitCode::FAILURE
        }
    }
}
