use agent_dump_core::output::{i18n::t, render};
use agent_dump_core::query::read::Page;
use serde_json::json;
use std::io::Write;

pub fn prompt(uri: &str, zh: bool) -> crate::Result<String> {
    if uri.len() > 4096 {
        return Err(t("READ_OPTIONS_INVALID", zh, &[]).into());
    }
    let executable = agent_dump_core::storage::source_io::path_text(
        &std::env::current_exe()?,
    );
    let command = |args: &[&str]| {
        let argv: Vec<_> = [executable.clone(), uri.into()]
            .into_iter()
            .chain(args.iter().map(|s| (*s).into()))
            .collect();
        json!({"argv": argv, "command": crate::command::shell_command(&argv)})
    };
    let commands = json!({
        "uri": uri,
        "shell": if cfg!(windows) { "PowerShell" } else { "POSIX" },
        "read": command(&["--read", "--json"]),
        "continue": command(&["--read", "--cursor", "CURSOR", "--json"]),
        "filter": command(&["--read", "--role", "user", "--match", "PHRASE", "--json"]),
        "details": command(&["--read", "--details", "--json"]),
        "oldest_first": command(&["--read", "--order", "asc", "--json"]),
        "head": command(&["--head"])
    });
    let template = if zh {
        include_str!("../../resources/prompts/read-session-zh.txt")
    } else {
        include_str!("../../resources/prompts/read-session-en.txt")
    };
    Ok(template.replace(
        "__COMMANDS_JSON__",
        &serde_json::to_string_pretty(&commands)?,
    ))
}

pub fn write_page(
    page: &Page,
    json: bool,
    incomplete: bool,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<()> {
    if json {
        serde_json::to_writer(
            &mut *out,
            &json!({
                "schema_version": 1,
                "kind": "read",
                "status": if incomplete { "partial" } else { "ok" },
                "data": page,
                "has_more": page.next_cursor.is_some()
            }),
        )?;
        writeln!(out)?;
    } else {
        write!(out, "{}", render::read_page(page))?;
        if incomplete {
            writeln!(out, "{}", t("READ_PARTIAL", zh, &[]))?;
        }
        writeln!(
            out,
            "{}",
            t(
                if page.next_cursor.is_some() {
                    "READ_NEXT"
                } else {
                    "READ_END"
                },
                zh,
                &[("cursor", page.next_cursor.clone().unwrap_or_default())],
            )
        )?;
    }
    Ok(())
}
