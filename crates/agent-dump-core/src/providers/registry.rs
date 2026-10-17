use crate::providers::contract::{Provider, ProviderInfo};

pub struct Registration {
    pub info: ProviderInfo,
    pub open: fn() -> crate::Result<Box<dyn Provider>>,
}

static REGISTRATIONS: &[Registration] = &[
    Registration {
        info: ProviderInfo {
            name: "opencode",
            display_name: "OpenCode",
            scheme: "opencode",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::sqlite::SqliteProvider::open(
                crate::providers::sqlite::Kind::OpenCode,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "zcode",
            display_name: "ZCode",
            scheme: "zcode",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::sqlite::SqliteProvider::open(
                crate::providers::sqlite::Kind::ZCode,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "codex",
            display_name: "Codex",
            scheme: "codex",
            identifier_label: "<session_id>",
            uri_prefixes: &["threads/"],
        },
        open: || Ok(Box::new(crate::providers::codex::Codex::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "kimi",
            display_name: "Kimi",
            scheme: "kimi",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::providers::kimi::Kimi::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "kimi-code",
            display_name: "Kimi-Code",
            scheme: "kimi-code",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::providers::kimi_code::KimiCode::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "claudecode",
            display_name: "Claude Code",
            scheme: "claude",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::claude::Claude::open(
                crate::providers::claude::Kind::Claude,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "qoder",
            display_name: "Qoder",
            scheme: "qoder",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::claude::Claude::open(
                crate::providers::claude::Kind::Qoder,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "qoder-cn",
            display_name: "Qoder CN",
            scheme: "qoder-cn",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::claude::Claude::open(
                crate::providers::claude::Kind::QoderCn,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "cursor",
            display_name: "Cursor",
            scheme: "cursor",
            identifier_label: "<composer_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::providers::cursor::Cursor::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "grok",
            display_name: "Grok",
            scheme: "grok",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::providers::grok::Grok::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "pi",
            display_name: "Pi",
            scheme: "pi",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::pi::Pi::open(
                crate::providers::pi::Kind::Pi,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "omp",
            display_name: "oh-my-pi",
            scheme: "omp",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::pi::Pi::open(
                crate::providers::pi::Kind::Omp,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "gemini-cli",
            display_name: "Gemini CLI",
            scheme: "gemini-cli",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::providers::gemini_cli::GeminiCli::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "dsh",
            display_name: "DSH",
            scheme: "dsh",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::providers::dsh::Dsh::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "deepchat",
            display_name: "DeepChat",
            scheme: "deepchat",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::desktop::Desktop::open(
                crate::providers::desktop::Kind::DeepChat,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "cherry",
            display_name: "Cherry Studio",
            scheme: "cherry",
            identifier_label: "topic-<id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::desktop::Desktop::open(
                crate::providers::desktop::Kind::Cherry,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "minimax",
            display_name: "MiniMax Code",
            scheme: "minimax",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(crate::providers::desktop::Desktop::open(
                crate::providers::desktop::Kind::MiniMax,
            )?))
        },
    },
    Registration {
        info: ProviderInfo {
            name: "antigravity-cli",
            display_name: "Antigravity CLI",
            scheme: "antigravity-cli",
            identifier_label: "<conversation_id>",
            uri_prefixes: &[],
        },
        open: || {
            Ok(Box::new(
                crate::providers::antigravity_cli::AntigravityCli::open()?,
            ))
        },
    },
];
pub fn all() -> &'static [Registration] {
    REGISTRATIONS
}

pub fn for_name(name: &str) -> crate::Result<&'static Registration> {
    REGISTRATIONS
        .iter()
        .find(|registration| registration.info.name == name)
        .ok_or_else(|| {
            format!("Provider not implemented in Rust: {name}").into()
        })
}
pub fn for_uri(uri: &str) -> Option<(&'static Registration, &str)> {
    let (scheme, mut id) = uri.split_once("://")?;
    // Python's URI regex allows one trailing newline, outside the captured id.
    id = id.strip_suffix('\n').unwrap_or(id);
    if id.contains('\n') {
        return None;
    }
    let registration = REGISTRATIONS
        .iter()
        .find(|registration| registration.info.scheme == scheme)?;
    for prefix in registration.info.uri_prefixes {
        if let Some(stripped) = id.strip_prefix(prefix) {
            id = stripped;
            break;
        }
    }
    (!id.is_empty()).then_some((registration, id))
}

pub fn search_roots() -> crate::Result<Vec<String>> {
    let mut roots = Vec::new();
    for registration in all() {
        let provider = (registration.open)()?;
        roots.extend(
            crate::providers::contract::source_roots(provider.as_ref())?
                .into_iter()
                .map(|root| {
                    format!("{}: {root}", registration.info.display_name)
                }),
        );
    }
    Ok(roots)
}

pub fn inside_source(path: &std::path::Path) -> crate::Result<bool> {
    let resolve = |path: &std::path::Path| {
        // An absolute path keeps project_path from expanding a literal `~`.
        crate::query::project_path(&crate::storage::source_io::path_text(
            &std::path::absolute(path)?,
        ))
    };
    let target = resolve(path)?;
    Ok(all().iter().any(|registration| {
        (registration.open)()
            .and_then(|mut provider| {
                Ok(match provider.select_source()? {
                    Some(root) => target.starts_with(resolve(root)?),
                    None => false,
                })
            })
            .unwrap_or(false)
    }))
}

pub fn uri_examples() -> Vec<String> {
    let mut examples = Vec::new();
    for registration in all() {
        let info = &registration.info;
        examples.push(format!("- {}://{}", info.scheme, info.identifier_label));
        examples.extend(info.uri_prefixes.iter().map(|prefix| {
            format!("- {}://{prefix}{}", info.scheme, info.identifier_label)
        }));
    }
    examples
}
