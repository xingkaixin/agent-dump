use agent_dump_core::output::i18n::terminal;
use std::collections::HashMap;
use std::ffi::OsString;

pub fn expand(args: Vec<OsString>, zh: bool) -> crate::Result<Vec<OsString>> {
    let Some(index) = args.iter().position(|s| s == "--shortcut") else {
        return Ok(args);
    };
    let Some(name) = args
        .get(index + 1)
        .and_then(|s| s.to_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
    else {
        return Err(terminal("SHORTCUT_MISSING_NAME", zh, &[]).into());
    };
    let end = (index + 2..args.len())
        .find(|&i| args[i].to_string_lossy().starts_with('-'))
        .unwrap_or(args.len());
    let config = agent_dump_core::config::Config::load()?;
    config.require_valid(zh)?;
    let Some((_, shortcut)) =
        config.shortcuts().into_iter().find(|(n, _)| n == name)
    else {
        return Err(terminal(
            "SHORTCUT_NOT_FOUND",
            zh,
            &[("name", name.into())],
        )
        .into());
    };
    let count = end - index - 2;
    if count != shortcut.params.len() {
        return Err(terminal(
            "SHORTCUT_ARGS_MISMATCH",
            zh,
            &[
                ("name", name.into()),
                ("expected", shortcut.params.len().to_string()),
                ("actual", count.to_string()),
            ],
        )
        .into());
    }
    let mut variables: HashMap<_, _> = shortcut
        .params
        .into_iter()
        .zip(
            args[index + 2..end]
                .iter()
                .map(|s| s.to_string_lossy().into_owned()),
        )
        .collect();
    if let Some(raw) = variables.get("date") {
        let date = crate::date_input::parse(raw)
            .ok_or_else(|| terminal("SHORTCUT_DATE_INVALID", zh, &[]))?;
        for (name, format) in [
            ("date", "%Y%m%d"),
            ("year", "%Y"),
            ("month", "%m"),
            ("year_month", "%Y-%m"),
        ] {
            variables.insert(name.into(), date.strftime(format).to_string());
        }
    }
    let mut expanded = args[..index].to_vec();
    for template in &shortcut.args {
        expanded.push(render(template, &variables, zh)?.into());
    }
    expanded.extend_from_slice(&args[end..]);
    Ok(expanded)
}

fn render(
    template: &str,
    variables: &HashMap<String, String>,
    zh: bool,
) -> crate::Result<String> {
    let invalid = || terminal("SHORTCUT_TEMPLATE_INVALID", zh, &[]);
    let mut chars = template.chars().peekable();
    let mut output = String::new();
    while let Some(c) = chars.next() {
        match c {
            '{' | '}' if chars.peek() == Some(&c) => {
                output.push(c);
                chars.next();
            }
            '{' => {
                let mut key = String::new();
                loop {
                    match chars.next() {
                        Some('}') => break,
                        Some(':') if chars.next() == Some('}') => break,
                        Some('{' | ':' | '!') | None => {
                            return Err(invalid().into());
                        }
                        Some(c) => key.push(c),
                    }
                }
                let value = variables.get(&key).ok_or_else(|| {
                    terminal("SHORTCUT_UNKNOWN_VARIABLE", zh, &[("name", key)])
                })?;
                output.push_str(value);
            }
            '}' => return Err(invalid().into()),
            _ => output.push(c),
        }
    }
    if output.starts_with('~') {
        output = agent_dump_core::storage::source_io::path_text(
            &agent_dump_core::config::expand_home(&output)?,
        );
    }
    Ok(output)
}
