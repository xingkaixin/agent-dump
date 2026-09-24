use crate::output_formats::OutputFormat;
use crate::provider::{Provider, ProviderInfo, RecoverableDiagnostic, SessionFailure};
use crate::provider_error::{self, ProviderError};
use crate::render::safe_line;
use std::fmt::Write;

pub fn record_warning(diagnostic: &RecoverableDiagnostic, zh: bool) -> String {
    match diagnostic {
        RecoverableDiagnostic::MessageConvertFailed(error) => {
            let error = safe_line(error);
            if zh {
                format!("警告: 转换消息格式失败: {error}")
            } else {
                format!("⚠️  Failed to convert message format: {error}")
            }
        }
        RecoverableDiagnostic::PiRecordConvertFailed(error) => {
            let error = safe_line(error);
            if zh {
                format!("警告: 转换 Pi 记录失败: {error}")
            } else {
                format!("⚠️  Failed to convert Pi record: {error}")
            }
        }
        RecoverableDiagnostic::TitleCacheFailed(error) => {
            let error = safe_line(error);
            if zh {
                format!("警告: 加载标题缓存失败: {error}")
            } else {
                format!("⚠️  Failed to load title cache: {error}")
            }
        }
        RecoverableDiagnostic::TitleCacheEntriesSkipped { path, count } => {
            let path = safe_line(&crate::source_io::path_text(path));
            if zh {
                format!("警告: {path} 跳过了 {count} 条格式错误的标题缓存记录")
            } else {
                format!("⚠️  {path}: skipped {count} malformed title cache entries")
            }
        }
        RecoverableDiagnostic::JsonlRecordsSkipped { path, count, lines } => {
            let path = safe_line(&crate::source_io::path_text(path));
            let lines = lines
                .iter()
                .map(usize::to_string)
                .collect::<Vec<_>>()
                .join(", ");
            if zh {
                format!("警告: {path} 跳过了 {count} 条格式错误的记录（行 {lines}）")
            } else {
                format!("⚠️  {path}: skipped {count} malformed records (lines {lines})")
            }
        }
        RecoverableDiagnostic::MessageDataParseFailed(id) => {
            let id = safe_line(id);
            if zh {
                format!("警告: 解析消息数据失败 message={id}")
            } else {
                format!("⚠️  Failed to parse message data message={id}")
            }
        }
        RecoverableDiagnostic::PartDataParseFailed(id) => {
            let id = safe_line(id);
            if zh {
                format!("警告: 解析消息分段数据失败 part={id}")
            } else {
                format!("⚠️  Failed to parse message part data part={id}")
            }
        }
    }
}

#[derive(Default)]
pub struct Diagnostic {
    summary: String,
    uri: Option<ParsedUri>,
    details: Vec<String>,
    roots: Vec<String>,
    capability: Option<String>,
    next_steps: Vec<String>,
}

struct ParsedUri {
    raw: String,
    scheme: Option<String>,
    id: Option<String>,
}

impl Diagnostic {
    pub fn unexpected(error: &(dyn std::error::Error + 'static), zh: bool) -> Self {
        Self {
            summary: if zh { "命令因未预期的错误中止。" } else { "Command aborted with an unexpected error." }.into(),
            details: vec![provider_error::operation_message(error, zh)],
            next_steps: if zh {
                ["重试一次以确认是否为瞬时故障。", "若可稳定复现，请带上上面的错误类型与命令参数提交 issue。"]
            } else {
                ["Retry once to check whether the failure is transient.", "If it reproduces consistently, open an issue with the error type above and your command arguments."]
            }.into_iter().map(str::to_owned).collect(),
            ..Self::default()
        }
    }
    pub fn invalid_uri(uri: &str, examples: Vec<String>, zh: bool) -> Self {
        let mut next_steps = vec![
            if zh {
                "改用受支持的 URI scheme。"
            } else {
                "Use a supported URI scheme."
            }
            .into(),
        ];
        next_steps.extend(examples);
        Self {
            summary: if zh {
                "URI 格式无效。"
            } else {
                "Invalid URI format."
            }
            .into(),
            uri: Some(ParsedUri {
                raw: uri.into(),
                scheme: None,
                id: None,
            }),
            details: vec![
                if zh {
                    "无法解析为受支持的 `<scheme>://<session_id>` 形式。"
                } else {
                    "Cannot be parsed as the supported `<scheme>://<session_id>` form."
                }
                .into(),
            ],
            next_steps,
            ..Self::default()
        }
    }

    pub fn missing_session(
        uri: &str,
        scheme: &str,
        id: &str,
        roots: Vec<String>,
        zh: bool,
    ) -> Self {
        Self {
            summary: if zh {
                "未找到匹配的会话。"
            } else {
                "No matching session found."
            }
            .into(),
            uri: Some(ParsedUri {
                raw: uri.into(),
                scheme: Some(scheme.into()),
                id: Some(id.into()),
            }),
            details: vec![
                if zh {
                    "已扫描当前可用 provider，但未匹配到该 session id。"
                } else {
                    "Scanned the currently available providers, but no session id matched."
                }
                .into(),
            ],
            roots,
            next_steps: if zh {
                vec![
                    "先运行 `agent-dump --list` 确认该会话是否仍存在。".into(),
                    "检查 URI 中的 session id 是否完整且对应正确 provider。".into(),
                ]
            } else {
                vec!["Run `agent-dump --list` to confirm the session still exists.".into(), "Check that the session id in the URI is complete and belongs to that provider.".into()]
            },
            ..Self::default()
        }
    }

    pub fn unsupported_formats(
        info: &ProviderInfo,
        provider: &dyn Provider,
        formats: &[OutputFormat],
        zh: bool,
    ) -> Option<Self> {
        let unsupported: Vec<_> = formats
            .iter()
            .filter(|format| !provider.supports_format(**format))
            .map(|format| format.name())
            .collect();
        if unsupported.is_empty() {
            return None;
        }
        let supported = [
            OutputFormat::Json,
            OutputFormat::Markdown,
            OutputFormat::Print,
            OutputFormat::Raw,
        ]
        .into_iter()
        .filter(|format| provider.supports_format(*format))
        .map(OutputFormat::name)
        .collect::<Vec<_>>()
        .join(", ");
        let requested = unsupported.join(",");
        let remove = unsupported
            .iter()
            .map(|name| format!("`{name}`"))
            .collect::<Vec<_>>()
            .join(", ");
        let name = info.display_name;
        Some(Self {
            summary: if zh {
                format!("当前请求了 {name} 不支持的导出能力。")
            } else {
                format!("The current request uses an export capability {name} does not support.")
            },
            capability: Some(if zh {
                format!("{name} 仅支持 {supported}；当前请求了 {requested}")
            } else {
                format!("{name} supports only {supported}; requested {requested}")
            }),
            next_steps: if zh {
                vec![
                    format!("移除 {remove}，改用支持的格式。"),
                    "若需要进一步处理，先导出 JSON 再做转换。".into(),
                ]
            } else {
                vec![
                    format!("Remove {remove} and use a supported format."),
                    "For further processing, export JSON first and convert afterwards.".into(),
                ]
            },
            ..Self::default()
        })
    }

    pub fn read_failed(
        error: &(dyn std::error::Error + 'static),
        roots: Vec<String>,
        zh: bool,
    ) -> Self {
        let error = provider_error::original(error);
        if let Some(ProviderError::Diagnostic {
            summary,
            details,
            roots,
            capability,
            next_steps,
        }) = error.downcast_ref::<ProviderError>()
        {
            return Self {
                summary: summary[usize::from(zh)].into(),
                details: details.clone(),
                roots: roots.clone(),
                capability: capability.map(|text| text[usize::from(zh)].into()),
                next_steps: next_steps
                    .iter()
                    .map(|text| text[usize::from(zh)].into())
                    .collect(),
                ..Self::default()
            };
        }
        Self {
            summary: if zh {
                "读取会话数据失败。"
            } else {
                "Failed to read session data."
            }
            .into(),
            details: vec![provider_error::message(error, zh)],
            roots,
            next_steps: if zh {
                vec![
                    "检查本地会话源文件或数据库是否仍存在。".into(),
                    "若问题持续，先用 `agent-dump --list` 缩小范围再重试。".into(),
                ]
            } else {
                vec![
                    "Check whether the local session source file or database still exists.".into(),
                    "If it persists, narrow the scope with `agent-dump --list` and retry.".into(),
                ]
            },
            ..Self::default()
        }
    }

    pub fn empty_list(providers: Option<&str>, roots: Vec<String>, zh: bool) -> Self {
        let summary = match (zh, providers) {
            (true, Some(_)) => "查询范围内没有可用 provider。",
            (false, Some(_)) => "No usable provider within the query scope.",
            (true, None) => "未找到任何可用的本地会话数据。",
            (false, None) => "No usable local session data found.",
        };
        let steps: &[&str] = match (zh, providers) {
            (true, Some(_)) => &[
                "确认这些 provider 在本机上确实存在会话数据。",
                "放宽 providers 范围，或先不加 provider 过滤执行 `--list`。",
            ],
            (false, Some(_)) => &[
                "Confirm those providers actually have session data on this machine.",
                "Widen the providers scope, or run `--list` without a provider filter first.",
            ],
            (true, None) => &[
                "确认对应 agent 已在本机生成过会话数据。",
                "若使用自定义目录，检查相关环境变量是否指向正确位置。",
                "若在开发环境，检查 `data/<agent>` 回退目录是否存在。",
            ],
            (false, None) => &[
                "Confirm the agent has produced session data on this machine.",
                "If you use a custom directory, check that the relevant environment variable points at it.",
                "In a development environment, check whether the `data/<agent>` fallback directory exists.",
            ],
        };
        Self {
            summary: summary.into(),
            details: providers
                .map(|names| format!("query providers: {names}"))
                .into_iter()
                .collect(),
            roots,
            next_steps: steps.iter().map(|step| (*step).into()).collect(),
            ..Self::default()
        }
    }

    pub fn render(&self, zh: bool) -> String {
        let mut output = format!(
            "{}\n{}: {}\n",
            if zh { "诊断信息" } else { "Diagnostic" },
            if zh { "结论" } else { "Summary" },
            safe_line(&self.summary)
        );
        if let Some(uri) = &self.uri {
            writeln!(
                output,
                "{}: {}",
                if zh { "解析后的 URI" } else { "Parsed URI" },
                safe_line(&uri.raw)
            )
            .unwrap();
            for (label, value) in [("scheme", &uri.scheme), ("session_id", &uri.id)] {
                if let Some(value) = value {
                    writeln!(output, "  - {label}: {}", safe_line(value)).unwrap();
                }
            }
        }
        append_items(
            &mut output,
            if zh { "证据" } else { "Details" },
            &self.details,
        );
        append_items(
            &mut output,
            if zh {
                "已检查路径"
            } else {
                "Searched roots"
            },
            &self.roots,
        );
        if let Some(capability) = &self.capability {
            writeln!(
                output,
                "{}: {}",
                if zh { "缺失能力" } else { "Capability gap" },
                safe_line(capability)
            )
            .unwrap();
        }
        append_items(
            &mut output,
            if zh { "下一步" } else { "Next steps" },
            &self.next_steps,
        );
        output
    }
}

fn append_items(output: &mut String, label: &str, items: &[String]) {
    if !items.is_empty() {
        writeln!(output, "{label}:").unwrap();
        for item in items.iter().filter(|item| !item.is_empty()) {
            writeln!(output, "  - {}", safe_line(item)).unwrap();
        }
    }
}

pub fn session_warning(provider: &ProviderInfo, failure: &SessionFailure, zh: bool) -> String {
    let source = safe_line(&failure.source);
    let error = safe_line(&provider_error::message(failure.error.as_ref(), zh));
    if matches!(provider.name, "cherry" | "minimax") {
        let name = provider.display_name;
        if zh {
            format!("读取 {name} 会话 {source} 失败：{error}")
        } else {
            format!("Failed to read {name} session {source}: {error}")
        }
    } else if zh {
        format!("警告: 解析会话文件失败 {source}: {error}")
    } else {
        format!("⚠️  Failed to parse session file {source}: {error}")
    }
}

pub fn lookup_warning(
    provider: &ProviderInfo,
    error: &(dyn std::error::Error + 'static),
    zh: bool,
) -> String {
    let name = provider.display_name;
    let error = safe_line(&provider_error::message(error, zh));
    if zh {
        format!("警告: {name} 查找会话失败: {error}")
    } else {
        format!("⚠️  {name} session lookup failed: {error}")
    }
}
