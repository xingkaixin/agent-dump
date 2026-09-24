use crate::provider::{Provider, ProviderInfo};

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
            Ok(Box::new(crate::sqlite_provider::SqliteProvider::open(
                crate::sqlite_provider::Kind::OpenCode,
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
            Ok(Box::new(crate::sqlite_provider::SqliteProvider::open(
                crate::sqlite_provider::Kind::ZCode,
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
        open: || Ok(Box::new(crate::codex::Codex::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "kimi",
            display_name: "Kimi",
            scheme: "kimi",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::kimi::Kimi::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "claudecode",
            display_name: "Claude Code",
            scheme: "claude",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::claude::Claude::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "cursor",
            display_name: "Cursor",
            scheme: "cursor",
            identifier_label: "<requestid>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::cursor::Cursor::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "pi",
            display_name: "Pi",
            scheme: "pi",
            identifier_label: "<session_id>",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::pi::Pi::open()?)),
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
            Ok(Box::new(crate::desktop::Desktop::open(
                crate::desktop::Kind::DeepChat,
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
            Ok(Box::new(crate::desktop::Desktop::open(
                crate::desktop::Kind::Cherry,
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
            Ok(Box::new(crate::desktop::Desktop::open(
                crate::desktop::Kind::MiniMax,
            )?))
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
        .ok_or_else(|| format!("Provider not implemented in Rust: {name}").into())
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
            crate::provider::source_roots(provider.as_ref())?
                .into_iter()
                .map(|root| format!("{}: {root}", registration.info.display_name)),
        );
    }
    Ok(roots)
}

pub fn uri_examples() -> Vec<String> {
    let mut examples = Vec::new();
    for registration in all() {
        let info = &registration.info;
        examples.push(format!("- {}://{}", info.scheme, info.identifier_label));
        examples.extend(
            info.uri_prefixes
                .iter()
                .map(|prefix| format!("- {}://{prefix}{}", info.scheme, info.identifier_label)),
        );
    }
    examples
}
