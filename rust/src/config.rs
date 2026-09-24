use crate::i18n::{t, terminal};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use toml_edit::{DocumentMut, Item};

#[derive(Clone)]
pub struct AiConfig {
    pub provider: String,
    pub base_url: String,
    pub model: String,
    pub api_key: String,
}

pub struct CollectConfig {
    pub concurrency: usize,
    pub timeout: u64,
    pub denies: BTreeMap<String, Vec<String>>,
}

pub struct LoggingConfig {
    pub enabled: bool,
    pub path: PathBuf,
}

pub struct Shortcut {
    pub params: Vec<String>,
    pub args: Vec<String>,
}

#[derive(Clone, Copy, PartialEq)]
pub enum ParseMode {
    Toml,
    Legacy,
    Invalid,
}

pub struct Config {
    pub path: PathBuf,
    pub mode: ParseMode,
    pub exists: bool,
    pub document: DocumentMut,
    data: Value,
}

pub fn config_path() -> crate::Result<PathBuf> {
    if cfg!(windows) {
        for name in ["APPDATA", "LOCALAPPDATA"] {
            if let Some(path) = std::env::var_os(name).filter(|s| !s.is_empty()) {
                return Ok(PathBuf::from(path).join("agent-dump/config.toml"));
            }
        }
    }
    crate::file_sessions::environment_root("HOME", ".config/agent-dump/config.toml")
}

fn json_item(item: &Item) -> Value {
    match item {
        Item::None => Value::Null,
        Item::Table(table) => Value::Object(
            table
                .iter()
                .map(|(k, v)| (k.into(), json_item(v)))
                .collect(),
        ),
        Item::ArrayOfTables(tables) => Value::Array(
            tables
                .iter()
                .map(|table| {
                    Value::Object(
                        table
                            .iter()
                            .map(|(k, v)| (k.into(), json_item(v)))
                            .collect(),
                    )
                })
                .collect(),
        ),
        Item::Value(value) => json_value(value),
    }
}

fn json_value(value: &toml_edit::Value) -> Value {
    match value {
        toml_edit::Value::String(value) => value.value().clone().into(),
        toml_edit::Value::Integer(value) => (*value.value()).into(),
        toml_edit::Value::Float(value) => crate::python_json::float(*value.value()).into(),
        toml_edit::Value::Boolean(value) => (*value.value()).into(),
        toml_edit::Value::Datetime(value) => value.value().to_string().into(),
        toml_edit::Value::Array(array) => Value::Array(array.iter().map(json_value).collect()),
        toml_edit::Value::InlineTable(table) => Value::Object(
            table
                .iter()
                .map(|(k, v)| (k.into(), json_value(v)))
                .collect(),
        ),
    }
}

fn repair_legacy(text: &str) -> String {
    use std::sync::LazyLock;
    static PATH: LazyLock<regex::Regex> =
        LazyLock::new(|| regex::Regex::new(r#""[A-Za-z]:\\[^"\r\n]*""#).unwrap());
    static SLASH: LazyLock<regex::Regex> = LazyLock::new(|| regex::Regex::new(r"\\+").unwrap());
    PATH.replace_all(text, |capture: &regex::Captures<'_>| {
        SLASH
            .replace_all(&capture[0], |run: &regex::Captures<'_>| {
                if run[0].len().is_multiple_of(2) {
                    run[0].to_owned()
                } else {
                    format!("{}\\", &run[0])
                }
            })
            .into_owned()
    })
    .into_owned()
}

impl Config {
    pub fn load() -> crate::Result<Self> {
        Self::at(&config_path()?)
    }

    pub fn at(path: &Path) -> crate::Result<Self> {
        let exists = path.exists();
        let source = if exists {
            let bytes = crate::source_io::read(path)?;
            std::str::from_utf8(&bytes)
                .map_err(|error| crate::python_json::invalid_utf8(&bytes, error))?
                .replace("\r\n", "\n")
                .replace('\r', "\n")
        } else {
            String::new()
        };
        let (mode, document) = match source.parse::<DocumentMut>() {
            Ok(document) => (ParseMode::Toml, document),
            Err(_) => match repair_legacy(&source).parse::<DocumentMut>() {
                Ok(document) => (ParseMode::Legacy, document),
                Err(_) => (ParseMode::Invalid, DocumentMut::new()),
            },
        };
        let data = Value::Object(
            document
                .iter()
                .map(|(k, v)| (k.into(), json_item(v)))
                .collect(),
        );
        Ok(Self {
            path: path.into(),
            mode,
            exists,
            document,
            data,
        })
    }

    pub fn require_valid(&self, zh: bool) -> crate::Result<()> {
        if self.mode == ParseMode::Invalid {
            return Err(terminal(
                "CONFIG_PARSE_INVALID",
                zh,
                &[("path", crate::source_io::path_text(&self.path))],
            )
            .into());
        }
        Ok(())
    }

    pub fn ai(&self) -> Option<AiConfig> {
        self.data["ai"].as_object().map(|_| AiConfig {
            provider: text(&self.data["ai"]["provider"]),
            base_url: text(&self.data["ai"]["base_url"]),
            model: text(&self.data["ai"]["model"]),
            api_key: text(&self.data["ai"]["api_key"]),
        })
    }

    pub fn output(&self) -> String {
        text(&self.data["export"]["output"])
    }

    pub fn collect(&self) -> CollectConfig {
        let mut denies = BTreeMap::new();
        if let Some(agents) = self.data["agent"].as_object() {
            for (name, values) in agents {
                if let Some(paths) = strings(&values["deny"]).filter(|v| !v.is_empty()) {
                    denies.insert(name.trim().into(), paths);
                }
            }
        }
        CollectConfig {
            concurrency: positive(&self.data["collect"]["summary_concurrency"], 4, Some(32))
                as usize,
            timeout: positive(&self.data["collect"]["summary_timeout_seconds"], 90, None),
            denies,
        }
    }

    pub fn validate_collect(&self) -> crate::Result<()> {
        if self.mode != ParseMode::Toml {
            return Err("TOML".into());
        }
        let Some(agents) = self.data.get("agent") else {
            return Ok(());
        };
        let agents = agents.as_object().ok_or("agent")?;
        for (name, values) in agents {
            let values = values.as_object().ok_or_else(|| format!("agent.{name}"))?;
            if let Some(deny) = values.get("deny") {
                let valid = deny.as_array().is_some_and(|paths| {
                    paths.iter().all(|path| {
                        path.as_str()
                            .is_some_and(|s| !s.trim().is_empty() && !s.contains('\0'))
                    })
                });
                if !valid {
                    return Err(format!("agent.{name}.deny").into());
                }
            }
        }
        Ok(())
    }

    pub fn logging(&self) -> crate::Result<LoggingConfig> {
        let enabled = match &self.data["logging"]["enabled"] {
            Value::Bool(value) => *value,
            Value::String(value) => !matches!(
                value.trim().to_lowercase().as_str(),
                "false" | "0" | "no" | "off"
            ),
            _ => true,
        };
        let path = text(&self.data["logging"]["path"]);
        let path = if path.is_empty() {
            self.path.parent().unwrap().join("logs/collect.log")
        } else {
            expand_home(&path)?
        };
        Ok(LoggingConfig { enabled, path })
    }

    pub fn shortcuts(&self) -> Vec<(String, Shortcut)> {
        let mut shortcuts = Vec::new();
        if let Some(values) = self.data["shortcut"].as_object() {
            for (name, shortcut) in values {
                if name.trim().is_empty() {
                    continue;
                }
                if let (Some(params), Some(args)) =
                    (strings(&shortcut["params"]), strings(&shortcut["args"]))
                    && !args.is_empty()
                {
                    shortcuts.push((name.trim().into(), Shortcut { params, args }));
                }
            }
        }
        shortcuts
    }

    pub fn write(&mut self, ai: Option<&AiConfig>, output: &str) -> crate::Result<()> {
        if self.mode != ParseMode::Toml {
            return Err("cannot safely update a configuration that is not valid TOML".into());
        }
        let values = ai.map(|ai| {
            [
                ("provider", &ai.provider),
                ("base_url", &ai.base_url),
                ("model", &ai.model),
                ("api_key", &ai.api_key),
            ]
        });
        update_section(
            &mut self.document,
            "ai",
            &["provider", "base_url", "model", "api_key"],
            values.as_ref().map_or(&[], |v| v.as_slice()),
        );
        update_section(
            &mut self.document,
            "export",
            &["output"],
            &[("output", &output.to_owned())],
        );
        crate::private_files::write_text(&self.path, &self.document.to_string())
    }
}

fn update_section(
    document: &mut DocumentMut,
    name: &str,
    keys: &[&str],
    values: &[(&str, &String)],
) {
    if document.get(name).and_then(Item::as_table_like).is_none() {
        if values.is_empty() {
            return;
        }
        document.remove(name);
        document[name] = Item::Table(toml_edit::Table::new());
    }
    let table = document[name].as_table_like_mut().unwrap();
    for key in keys {
        if !values.iter().any(|(name, _)| name == key) {
            table.remove(key);
        }
    }
    for (key, value) in values {
        let mut replacement = toml_edit::Value::from(value.as_str());
        if let Some(previous) = table.get(key).and_then(Item::as_value) {
            *replacement.decor_mut() = previous.decor().clone();
        }
        if let Some(slot) = table.get_mut(key) {
            *slot = Item::Value(replacement);
        } else {
            table.insert(key, Item::Value(replacement));
        }
    }
    if table.is_empty() {
        document.remove(name);
    }
}

fn text(value: &Value) -> String {
    value.as_str().unwrap_or("").trim().into()
}
fn strings(value: &Value) -> Option<Vec<String>> {
    value.as_array().map(|items| {
        items
            .iter()
            .map(|v| crate::value::string(v).trim().to_owned())
            .filter(|s| !s.is_empty())
            .collect()
    })
}
fn positive(value: &Value, default: u64, maximum: Option<u64>) -> u64 {
    if !value.is_string()
        && value
            .as_number()
            .is_none_or(|n| n.to_string().contains(['.', 'e', 'E']))
    {
        return default;
    }
    let value = crate::value::integer_number(value).as_u64();
    value
        .filter(|n| *n > 0 && maximum.is_none_or(|m| *n <= m))
        .unwrap_or(default)
}

pub fn expand_home(raw: &str) -> crate::Result<PathBuf> {
    if raw == "~" || raw.starts_with("~/") || (cfg!(windows) && raw.starts_with("~\\")) {
        return Ok(
            crate::file_sessions::environment_root("HOME", "")?.join(raw.get(2..).unwrap_or(""))
        );
    }
    Ok(raw.into())
}

pub fn validate_ai(config: Option<&AiConfig>, exists: bool) -> Vec<&'static str> {
    if !exists {
        return vec!["missing_file"];
    }
    let Some(config) = config else {
        return vec!["provider", "base_url", "model", "api_key"];
    };
    let mut errors = Vec::new();
    if !matches!(config.provider.as_str(), "openai" | "anthropic") {
        errors.push("provider");
    }
    if config.base_url.is_empty() {
        errors.push("base_url");
    }
    if config.model.is_empty() {
        errors.push("model");
    }
    if config.api_key.is_empty() {
        errors.push("api_key");
    }
    if !config.base_url.is_empty() {
        let scheme = config
            .base_url
            .split(':')
            .next()
            .unwrap_or("")
            .to_lowercase();
        if !matches!(scheme.as_str(), "http" | "https") {
            errors.push("base_url_scheme");
        } else if scheme == "http" && !config.api_key.is_empty() {
            let host = url::Url::parse(&config.base_url)
                .ok()
                .and_then(|url| url.host_str().map(str::to_owned))
                .unwrap_or_default();
            if !matches!(
                host.trim_matches(['[', ']']).to_lowercase().as_str(),
                "localhost" | "127.0.0.1" | "::1"
            ) {
                errors.push("base_url_plaintext_key");
            }
        }
    }
    errors
}

pub fn collect_ai_error(errors: &[&str], zh: bool) -> String {
    let key = if errors.contains(&"missing_file") {
        "COLLECT_CONFIG_MISSING"
    } else if errors.contains(&"base_url_scheme") {
        "COLLECT_CONFIG_BAD_SCHEME"
    } else if errors.contains(&"base_url_plaintext_key") {
        "COLLECT_CONFIG_PLAINTEXT_KEY"
    } else {
        "COLLECT_CONFIG_INCOMPLETE"
    };
    format!(
        "{}\n{}",
        t(key, zh, &[("fields", errors.join(","))]),
        t("COLLECT_CONFIG_HINT", zh, &[])
    )
}
