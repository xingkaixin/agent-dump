pub mod filter;
pub mod index;
pub mod scanner;
pub mod text;
pub mod transcript;

use crate::output::i18n::t;
use crate::query::text::{Mode, whitespace};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Component, PathBuf};

#[derive(Default)]
pub struct Query {
    pub providers: Option<BTreeSet<String>>,
    pub keyword: Option<String>,
    pub path: Option<PathBuf>,
    pub roles: Option<BTreeSet<String>>,
    pub limit: Option<usize>,
    pub mode: Mode,
}

fn error(key: &str, zh: bool) -> crate::Error {
    t(key, zh, &[]).into()
}

fn provider_name(name: &str) -> Option<String> {
    let name = name.trim().to_lowercase();
    let name = if name == "claude" {
        "claudecode"
    } else {
        &name
    };
    crate::providers::registry::for_name(name)
        .ok()
        .map(|_| name.into())
}

fn providers(raw: &str, zh: bool) -> crate::Result<BTreeSet<String>> {
    let names: Vec<_> = raw
        .split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .collect();
    if names.is_empty() {
        return Err(error("QUERY_ERROR_EMPTY_PROVIDERS", zh));
    }
    let unknown: BTreeSet<_> = names
        .iter()
        .filter(|s| provider_name(s).is_none())
        .map(|s| s.to_lowercase())
        .collect();
    if !unknown.is_empty() {
        return Err(t(
            "QUERY_ERROR_UNKNOWN_AGENT",
            zh,
            &[("name", unknown.into_iter().collect::<Vec<_>>().join(","))],
        )
        .into());
    }
    Ok(names.into_iter().filter_map(provider_name).collect())
}

fn roles(raw: &str, zh: bool) -> crate::Result<BTreeSet<String>> {
    let roles: BTreeSet<_> = raw
        .split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_lowercase)
        .collect();
    if roles.is_empty() {
        return Err(error("QUERY_ERROR_EMPTY_ROLES", zh));
    }
    Ok(roles)
}

fn limit(raw: &str, zh: bool) -> crate::Result<usize> {
    let raw: String = raw
        .trim_matches(whitespace)
        .chars()
        .map(crate::compat::value::decimal_digit)
        .collect();
    let raw = raw.as_str();
    if raw.is_empty() {
        return Err(error("QUERY_ERROR_EMPTY_LIMIT", zh));
    }
    let digits = raw.strip_prefix('+').unwrap_or(raw);
    let valid = !digits.starts_with('_')
        && !digits.ends_with('_')
        && !digits.contains("__")
        && digits.chars().all(|c| c.is_ascii_digit() || c == '_');
    if !valid {
        return Err(error("QUERY_ERROR_LIMIT_NOT_POSITIVE", zh));
    }
    let value: num_bigint::BigInt = digits
        .replace('_', "")
        .parse()
        .map_err(|_| error("QUERY_ERROR_LIMIT_NOT_POSITIVE", zh))?;
    if value <= 0.into() {
        return Err(error("QUERY_ERROR_LIMIT_NOT_POSITIVE", zh));
    }
    if value > i64::MAX.into() {
        return Err(error("QUERY_ERROR_LIMIT_TOO_LARGE", zh));
    }
    Ok(value.try_into()?)
}

pub fn project_path(raw: &str) -> crate::Result<PathBuf> {
    let raw = raw.trim();
    let path = crate::config::expand_home(raw)?;
    let absolute = std::path::absolute(path)?;
    let mut resolved = PathBuf::new();
    for component in absolute.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            _ => {
                resolved.push(component);
                if resolved.is_symlink() {
                    resolved = resolved.canonicalize()?;
                }
            }
        }
    }
    Ok(resolved)
}

fn path(raw: &str, zh: bool) -> crate::Result<PathBuf> {
    if raw.trim().is_empty() {
        return Err(error("QUERY_ERROR_EMPTY_PATH", zh));
    }
    project_path(raw)
}
pub fn shell_words(raw: &str) -> Option<Vec<String>> {
    let mut chars = raw.chars();
    let mut words = Vec::new();
    let mut word = String::new();
    let mut quote = None;
    let mut active = false;
    while let Some(c) = chars.next() {
        match (quote, c) {
            (Some('\''), '\'') | (Some('"'), '"') => {
                quote = None;
            }
            (None, '\'' | '"') => {
                quote = Some(c);
                active = true;
            }
            (None | Some('"'), '\\') => {
                let next = chars.next()?;
                if quote == Some('"') && !matches!(next, '\\' | '"') {
                    word.push('\\');
                }
                word.push(next);
                active = true;
            }
            (None, ' ' | '\t' | '\r' | '\n') => {
                if active {
                    words.push(std::mem::take(&mut word));
                    active = false;
                }
            }
            _ => {
                word.push(c);
                active = true;
            }
        }
    }
    if quote.is_some() {
        return None;
    }
    if active {
        words.push(word);
    }
    Some(words)
}

fn structured(token: &str) -> bool {
    token.split_once(':').is_some_and(|(key, _)| {
        matches!(
            key.trim().to_lowercase().as_str(),
            "provider" | "role" | "path" | "cwd" | "limit"
        )
    })
}

impl Query {
    pub fn parse(raw: &str, zh: bool) -> crate::Result<Self> {
        let raw = raw.trim_matches(whitespace);
        if raw.is_empty() {
            return Err(error("QUERY_ERROR_EMPTY_SPEC", zh));
        }
        let words = shell_words(raw);
        if raw.split(whitespace).any(structured)
            || words
                .as_ref()
                .is_some_and(|w| w.iter().any(|s| structured(s)))
        {
            let words =
                words.ok_or_else(|| error("QUERY_ERROR_INVALID_SYNTAX", zh))?;
            let mut query = Self::default();
            let mut keywords = Vec::new();
            for word in words {
                let Some((key, value)) = word.split_once(':') else {
                    keywords.push(word);
                    continue;
                };
                match key.trim().to_lowercase().as_str() {
                    "provider" => query.providers = Some(providers(value, zh)?),
                    "role" => query.roles = Some(roles(value, zh)?),
                    "path" | "cwd" => {
                        if query.path.is_some() {
                            return Err(error(
                                "QUERY_ERROR_DUPLICATE_PATH",
                                zh,
                            ));
                        }
                        query.path = Some(path(value, zh)?);
                    }
                    "limit" => {
                        if query.limit.is_some() {
                            return Err(error(
                                "QUERY_ERROR_DUPLICATE_LIMIT",
                                zh,
                            ));
                        }
                        query.limit = Some(limit(value, zh)?);
                    }
                    _ => {
                        return Err(t(
                            "QUERY_ERROR_UNKNOWN_FIELD",
                            zh,
                            &[("field", key.trim().into())],
                        )
                        .into());
                    }
                }
            }
            let keyword = keywords.join(" ").trim().to_owned();
            query.keyword = (!keyword.is_empty()).then_some(keyword);
            return Ok(query);
        }
        if let Some((scope, keyword)) = raw.split_once(':') {
            let names: Vec<_> = scope
                .split(',')
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .collect();
            if names.len() > 1
                || names.iter().any(|name| provider_name(name).is_some())
            {
                let providers = Some(providers(scope, zh)?);
                if keyword.trim().is_empty() {
                    return Err(error("QUERY_ERROR_EMPTY_KEYWORD", zh));
                }
                return Ok(Self {
                    providers,
                    keyword: Some(keyword.trim().into()),
                    ..Self::default()
                });
            }
        }
        Ok(Self {
            keyword: Some(raw.into()),
            ..Self::default()
        })
    }

    pub fn from_uri(raw: &str, zh: bool) -> crate::Result<Self> {
        let raw = raw.strip_prefix("agents://").ok_or("Invalid query URI")?;
        let raw = raw.split('#').next().unwrap_or(raw);
        let (location, params) = raw.split_once('?').unwrap_or((raw, ""));
        let path = Some(path(location, zh)?);
        let mut fields: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for pair in params.split('&').filter(|s| !s.is_empty()) {
            let (key, value) = pair.split_once('=').unwrap_or((pair, ""));
            fields.entry(decode(key)).or_default().push(decode(value));
        }
        let unknown = fields
            .keys()
            .filter(|k| {
                !matches!(k.as_str(), "q" | "providers" | "roles" | "limit")
            })
            .cloned()
            .collect::<Vec<_>>();
        if !unknown.is_empty() {
            return Err(t(
                "QUERY_ERROR_UNKNOWN_FIELD",
                zh,
                &[("field", unknown.join(", "))],
            )
            .into());
        }
        let mut query = Self {
            path,
            ..Self::default()
        };
        for name in ["q", "providers", "roles", "limit"] {
            let Some(values) = fields.get(name) else {
                continue;
            };
            if values.len() != 1 {
                return Err(t(
                    "QUERY_ERROR_DUPLICATE_FIELD",
                    zh,
                    &[("field", name.into())],
                )
                .into());
            }
            let raw = values[0].trim();
            match name {
                "q" => query.keyword = (!raw.is_empty()).then(|| raw.into()),
                "providers" => query.providers = Some(providers(raw, zh)?),
                "roles" => query.roles = Some(roles(raw, zh)?),
                "limit" => query.limit = Some(limit(raw, zh)?),
                _ => unreachable!(),
            }
        }
        Ok(query)
    }
    pub fn includes_path(&self, directory: &str) -> bool {
        let Some(scope) = &self.path else {
            return true;
        };
        !directory.trim().is_empty()
            && project_path(directory)
                .is_ok_and(|p| p.starts_with(scope) || scope.starts_with(p))
    }
    pub fn summary(&self, zh: bool) -> String {
        if self.path.is_none()
            && self.providers.is_none()
            && self.roles.is_none()
            && self.limit.is_none()
            && let Some(keyword) = &self.keyword
        {
            return crate::output::render::safe_line(keyword);
        }
        let mut parts = Vec::new();
        if let Some(path) = &self.path {
            parts.push(t(
                "QUERY_SUMMARY_PATH",
                zh,
                &[("path", crate::storage::source_io::path_text(path))],
            ));
        }
        if let Some(keyword) = &self.keyword {
            parts.push(t(
                "QUERY_SUMMARY_KEYWORD",
                zh,
                &[("keyword", keyword.clone())],
            ));
        }
        if let Some(providers) = &self.providers {
            parts.push(format!(
                "providers={}",
                providers.iter().cloned().collect::<Vec<_>>().join(",")
            ));
        }
        if let Some(roles) = &self.roles {
            parts.push(format!(
                "roles={}",
                roles.iter().cloned().collect::<Vec<_>>().join(",")
            ));
        }
        if let Some(limit) = self.limit {
            parts.push(format!("limit={limit}"));
        }
        crate::output::render::safe_line(&if parts.is_empty() {
            t("QUERY_SUMMARY_ALL_SESSIONS", zh, &[])
        } else {
            parts.join(&t("QUERY_SUMMARY_SEPARATOR", zh, &[]))
        })
    }
}

fn decode(raw: &str) -> String {
    let raw = raw.replace('+', " ");
    let bytes = raw.as_bytes();
    let mut result = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%'
            && i + 2 < bytes.len()
            && let (Some(a), Some(b)) = (
                (bytes[i + 1] as char).to_digit(16),
                (bytes[i + 2] as char).to_digit(16),
            )
        {
            result.push(
                u8::try_from(a * 16 + b).expect("two hex digits fit in a byte"),
            );
            i += 3;
            continue;
        }
        result.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&result).into_owned()
}
