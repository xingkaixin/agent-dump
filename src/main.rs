mod cli_args;
mod collect;
mod command;
mod date_input;
mod shortcut;
mod terminal;
mod workflows;

use cli_args::normalize_arguments;
use std::io::{self, Write};

use agent_dump_core::output::diagnostics;
pub use agent_dump_core::{Error, Result};

fn main() -> std::process::ExitCode {
    let arguments = normalize_arguments(std::env::args_os().collect());
    let emit = arguments.iter().any(|arg| arg == "--emit-prompt");
    let zh = cli_args::language(&arguments);
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
    let zh = cli_args::language(&arguments);
    let args = match cli_args::parse(normalize_arguments(arguments), zh) {
        Ok(args) => args,
        Err(error) => {
            let _ = error.print();
            return std::process::ExitCode::from(
                u8::try_from(error.exit_code())
                    .expect("Clap exit codes are 0 or 2"),
            );
        }
    };
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
                return std::process::ExitCode::from(
                    u8::try_from(error.exit_code())
                        .expect("Clap exit codes are 0 or 2"),
                );
            }
            if error
                .downcast_ref::<io::Error>()
                .is_some_and(|e| e.kind() == io::ErrorKind::BrokenPipe)
            {
                return std::process::ExitCode::SUCCESS;
            }
            let diagnostic =
                diagnostics::Diagnostic::unexpected(error.as_ref(), zh)
                    .render(zh);
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
