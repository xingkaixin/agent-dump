use crate::config::{AiConfig, Config, ParseMode};
use crate::i18n::{t, terminal};
use std::io::{BufRead, Write};

pub fn mask_key(value: &str) -> String {
    let chars: Vec<_> = value.chars().collect();
    if chars.len() <= 6 {
        return "*".repeat(chars.len());
    }
    format!(
        "{}{}{}",
        chars[..3].iter().collect::<String>(),
        "*".repeat(chars.len() - 6),
        chars[chars.len() - 3..].iter().collect::<String>()
    )
}

pub fn read_line(
    prompt: &str,
    out: &mut impl Write,
    input: &mut impl BufRead,
) -> crate::Result<String> {
    write!(out, "{prompt}")?;
    out.flush()?;
    let mut line = String::new();
    if input.read_line(&mut line)? == 0 {
        return Err(crate::provider_error::ProviderError::Cause {
            kind: "EOFError",
            message: "EOF when reading a line".into(),
        }
        .into());
    }
    Ok(line.trim().into())
}

fn fields(
    ai: Option<&AiConfig>,
    output: &str,
    zh: bool,
    out: &mut impl Write,
) -> crate::Result<()> {
    for (key, field, value) in [
        (
            "CONFIG_CONFIRM_PROVIDER",
            "provider",
            ai.map_or("", |ai| ai.provider.as_str()).to_owned(),
        ),
        (
            "CONFIG_CONFIRM_BASE_URL",
            "base_url",
            ai.map_or("", |ai| ai.base_url.as_str()).to_owned(),
        ),
        (
            "CONFIG_CONFIRM_MODEL",
            "model",
            ai.map_or("", |ai| ai.model.as_str()).to_owned(),
        ),
        (
            "CONFIG_CONFIRM_API_KEY",
            "api_key",
            mask_key(ai.map_or("", |ai| ai.api_key.as_str())),
        ),
        ("CONFIG_CONFIRM_EXPORT_OUTPUT", "output", output.to_owned()),
    ] {
        writeln!(out, "{}", terminal(key, zh, &[(field, value)]))?;
    }
    Ok(())
}

pub fn run(
    action: &str,
    zh: bool,
    out: &mut impl Write,
    input: &mut impl BufRead,
) -> crate::Result<bool> {
    let mut config = Config::load()?;
    let ai = config.ai();
    let output = config.output();
    if action == "view" && config.exists {
        writeln!(
            out,
            "{}",
            terminal(
                "CONFIG_VIEW_TITLE",
                zh,
                &[("path", crate::source_io::path_text(&config.path))]
            )
        )?;
        fields(
            ai.as_ref(),
            if output.is_empty() {
                "./sessions (default)"
            } else {
                &output
            },
            zh,
            out,
        )?;
        let collect = config.collect();
        let logging = config.logging()?;
        let shortcuts = config.shortcuts();
        writeln!(
            out,
            "  collect.summary_concurrency: {}",
            collect.concurrency
        )?;
        writeln!(
            out,
            "  collect.summary_timeout_seconds: {}",
            collect.timeout
        )?;
        writeln!(
            out,
            "  logging.enabled: {}",
            if logging.enabled { "True" } else { "False" }
        )?;
        writeln!(
            out,
            "  logging.path: {}",
            crate::render::safe_line(&crate::source_io::path_text(&logging.path))
        )?;
        writeln!(out, "  shortcuts.count: {}", shortcuts.len())?;
        for (name, shortcut) in shortcuts {
            writeln!(
                out,
                "{}",
                crate::render::safe_line(&format!(
                    "  shortcut.{name}: params={} args={}",
                    crate::value::repr(&serde_json::json!(shortcut.params)),
                    crate::value::repr(&serde_json::json!(shortcut.args))
                ))
            )?;
        }
        return Ok(true);
    }
    if action == "view" {
        writeln!(
            out,
            "{}",
            terminal(
                "CONFIG_NOT_FOUND",
                zh,
                &[("path", crate::source_io::path_text(&config.path))]
            )
        )?;
        let answer = read_line(
            &format!("{} (y/N): ", t("CONFIG_PROMPT_CREATE", zh, &[])),
            out,
            input,
        )?;
        if !matches!(answer.to_lowercase().as_str(), "y" | "yes") {
            return Ok(false);
        }
    } else if action != "edit" {
        writeln!(
            out,
            "{}",
            terminal("CONFIG_ACTION_INVALID", zh, &[("action", action.into())])
        )?;
        return Ok(false);
    }
    if config.mode != ParseMode::Toml {
        writeln!(
            out,
            "{}",
            terminal(
                "CONFIG_EDIT_REQUIRES_VALID_TOML",
                zh,
                &[("path", crate::source_io::path_text(&config.path))]
            )
        )?;
        return Ok(false);
    }
    let candidate = prompt(ai.as_ref(), &output, zh, out, input)?;
    let Some((ai, output)) = candidate else {
        writeln!(out, "{}", t("CONFIG_CANCELLED", zh, &[]))?;
        return Ok(false);
    };
    if let Some(ai) = &ai {
        let errors = crate::config::validate_ai(Some(ai), true);
        if !errors.is_empty() {
            writeln!(
                out,
                "{}",
                terminal(
                    "CONFIG_INVALID_FIELDS",
                    zh,
                    &[("fields", errors.join(", "))]
                )
            )?;
            return Ok(false);
        }
    }
    config.write(ai.as_ref(), &output)?;
    writeln!(
        out,
        "{}",
        terminal(
            "CONFIG_SAVED",
            zh,
            &[("path", crate::source_io::path_text(&config.path))]
        )
    )?;
    Ok(true)
}

type Edited = Option<(Option<AiConfig>, String)>;

fn prompt(
    existing: Option<&AiConfig>,
    old_output: &str,
    zh: bool,
    out: &mut impl Write,
    input: &mut impl BufRead,
) -> crate::Result<Edited> {
    let default_provider = existing.map_or("openai", |ai| ai.provider.as_str());
    let tty = crate::tui::available();
    let provider = if tty {
        out.flush()?;
        let rows = ["OpenAI", "Anthropic"].map(|name| crate::tui::Row {
            title: name.into(),
            detail: String::new(),
            group: String::new(),
        });
        let Some(selected) = crate::tui::select(
            &t("CONFIG_SELECT_PROVIDER", zh, &[]),
            &rows,
            false,
            usize::from(default_provider == "anthropic"),
            zh,
        )?
        else {
            return Ok(None);
        };
        if selected[0] == 0 {
            "openai"
        } else {
            "anthropic"
        }
    } else {
        writeln!(
            out,
            "{}\n1. OpenAI\n2. Anthropic",
            t("CONFIG_SELECT_PROVIDER", zh, &[])
        )?;
        let answer = read_line(&t("CONFIG_INPUT_PROMPT", zh, &[]), out, input)?;
        match answer.as_str() {
            "" => default_provider,
            "1" => "openai",
            "2" => "anthropic",
            _ => return Ok(None),
        }
    };
    let defaults = [
        existing.map_or("", |ai| ai.base_url.as_str()),
        existing.map_or("", |ai| ai.model.as_str()),
        existing.map_or("", |ai| ai.api_key.as_str()),
        old_output,
    ];
    let mut values = Vec::new();
    for ((key, secret), default) in [
        ("CONFIG_INPUT_BASE_URL", false),
        ("CONFIG_INPUT_MODEL", false),
        ("CONFIG_INPUT_API_KEY", true),
        ("CONFIG_INPUT_EXPORT_OUTPUT", false),
    ]
    .into_iter()
    .zip(defaults)
    {
        let shown = if secret {
            mask_key(default)
        } else {
            crate::render::safe_line(default)
        };
        if tty {
            let shown_default = if secret {
                default.to_owned()
            } else {
                crate::render::safe_line(default)
            };
            let Some(value) = crate::tui::input(&t(key, zh, &[]), &shown_default, secret, zh)?
            else {
                return Ok(None);
            };
            values.push(if value == shown_default {
                default.to_owned()
            } else {
                value
            });
        } else {
            let prompt = format!("{} [{shown}]: ", t(key, zh, &[]));
            use std::io::IsTerminal;
            let value = if secret && std::io::stdin().is_terminal() {
                out.flush()?;
                let Some(value) = crate::tui::secret_line(&prompt)? else {
                    return Ok(None);
                };
                value.trim().to_owned()
            } else {
                read_line(&prompt, out, input)?
            };
            values.push(if value.is_empty() {
                default.into()
            } else {
                value
            });
        }
    }
    let ai = (existing.is_some() || values[..3].iter().any(|v| !v.is_empty())).then(|| AiConfig {
        provider: provider.trim().into(),
        base_url: values[0].trim().into(),
        model: values[1].trim().into(),
        api_key: values[2].trim().into(),
    });
    let output = values[3].trim().to_owned();
    writeln!(out, "{}", t("CONFIG_CONFIRM_TITLE", zh, &[]))?;
    fields(ai.as_ref(), &output, zh, out)?;
    let confirmed = if tty {
        out.flush()?;
        crate::tui::confirm(&t("CONFIG_CONFIRM_WRITE", zh, &[]), true, zh)?
    } else {
        let answer = read_line(
            &format!("{} (y/N): ", t("CONFIG_CONFIRM_WRITE", zh, &[])),
            out,
            input,
        )?;
        matches!(answer.to_lowercase().as_str(), "y" | "yes")
    };
    if !confirmed || (ai.is_none() && output == old_output) {
        return Ok(None);
    }
    Ok(Some((ai, output)))
}
