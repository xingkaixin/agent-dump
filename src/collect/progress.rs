use agent_dump_core::output::i18n::t;
use agent_dump_core::output::render;
use std::io::Write;

pub fn progress(
    key: &str,
    values: &[(&str, String)],
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<()> {
    writeln!(warnings, "{}", render::safe_line(&t(key, zh, values)))?;
    Ok(())
}
