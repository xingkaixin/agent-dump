use crate::collect::model::Mode;
use agent_dump_core::config::AiConfig;
use serde_json::{Value, json};
use std::fmt;
use std::io::Read;
use std::time::Duration;

#[derive(Debug)]
pub struct RequestError {
    message: String,
    pub retryable: bool,
    rejected: Option<&'static str>,
}
impl fmt::Display for RequestError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.message)
    }
}
impl std::error::Error for RequestError {}

const fn error(message: String, retryable: bool) -> RequestError {
    RequestError {
        message,
        retryable,
        rejected: None,
    }
}

pub fn schema(mode: Mode) -> Value {
    let fields = mode.fields();
    let properties: serde_json::Map<_, _> = fields
        .iter()
        .map(|field| {
            (
                (*field).into(),
                json!({"type":"array", "items":{"type":"string"}, "maxItems":12}),
            )
        })
        .collect();
    json!({"name":"collect_summary", "schema":{"type":"object", "properties": properties, "required":fields, "additionalProperties":false}, "strict":true})
}

pub fn request(
    config: &AiConfig,
    prompt: &str,
    timeout: u64,
    structured: Option<Mode>,
) -> Result<String, RequestError> {
    content(config, &respond(config, prompt, timeout, structured)?)
}

fn respond(
    config: &AiConfig,
    prompt: &str,
    timeout: u64,
    structured: Option<Mode>,
) -> Result<Value, RequestError> {
    let system = include_str!("../../resources/prompts/system.txt");
    let openai = config.provider == "openai";
    let mut payload = if openai {
        json!({"model":config.model, "messages":[{"role":"system", "content":system}, {"role":"user", "content":prompt}], "temperature":0.2})
    } else {
        json!({"model":config.model, "max_tokens":4096, "system":system, "messages":[{"role":"user", "content":prompt}]})
    };
    if config.reasoning == "off" {
        if openai {
            payload["enable_thinking"] = false.into();
        } else {
            payload["thinking"] = json!({"type":"disabled"});
        }
    }
    if let Some(mode) = structured
        && openai
    {
        payload["max_tokens"] = 4096.into();
        payload["response_format"] =
            json!({"type":"json_schema", "json_schema":schema(mode)});
    }
    merge(&mut payload, &config.extra_body);
    loop {
        let result = post(config, &payload, timeout);
        let retry = match &result {
            Err(error) if openai => error.rejected.is_some_and(|param| {
                config.extra_body.get(param).is_none()
                    && drop_rejected(&mut payload, param)
            }),
            _ => false,
        };
        if !retry {
            return result;
        }
    }
}

fn merge(target: &mut Value, source: &Value) {
    if let (Value::Object(target), Value::Object(source)) = (target, source) {
        for (key, value) in source {
            match target.get_mut(key) {
                Some(slot) if slot.is_object() && value.is_object() => {
                    merge(slot, value);
                }
                _ => {
                    target.insert(key.clone(), value.clone());
                }
            }
        }
    }
}

fn drop_rejected(payload: &mut Value, param: &str) -> bool {
    let payload = payload.as_object_mut().unwrap();
    let Some(value) = payload.shift_remove(param) else {
        return false;
    };
    if param == "max_tokens" {
        payload.insert("max_completion_tokens".into(), value);
    }
    true
}

fn content(
    config: &AiConfig,
    response: &Value,
) -> Result<String, RequestError> {
    let provider = if config.provider == "openai" {
        "OpenAI"
    } else {
        "Anthropic"
    };
    let content = if config.provider == "openai" {
        response
            .get("choices")
            .and_then(|v| v.get(0))
            .and_then(|v| v.get("message"))
            .and_then(|v| v.get("content"))
    } else {
        response
            .get("content")
            .and_then(Value::as_array)
            .and_then(|blocks| blocks.iter().find_map(|v| v.get("text")))
    };
    let content = content.ok_or_else(|| {
        error(format!("{provider} API response missing content"), false)
    })?;
    let content = content
        .as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| {
            error(format!("{provider} API returned empty content"), false)
        })?;
    Ok(content.into())
}

fn post(
    config: &AiConfig,
    payload: &Value,
    timeout: u64,
) -> Result<Value, RequestError> {
    let provider = if config.provider == "openai" {
        "OpenAI"
    } else {
        "Anthropic"
    };
    let endpoint = if config.provider == "openai" {
        "chat/completions"
    } else {
        "messages"
    };
    let mut url = url::Url::parse(&format!(
        "{}/{endpoint}",
        config.base_url.trim_end_matches('/')
    ))
    .map_err(|e| error(format!("{provider} API request failed: {e}"), false))?;
    let origin = url.origin();
    let agent = ureq::Agent::new_with_config(
        ureq::Agent::config_builder()
            .timeout_global(Some(Duration::from_secs(timeout)))
            .max_redirects(0)
            .http_status_as_error(false)
            .build(),
    );
    let mut get = false;
    let mut credentials = true;
    for redirects in 0..=10 {
        let mut builder = if get {
            agent.get(url.as_str()).force_send_body()
        } else {
            agent.post(url.as_str())
        };
        if !get {
            builder = builder.header("Content-Type", "application/json");
        }
        if credentials {
            if config.provider == "openai" {
                builder = builder.header(
                    "Authorization",
                    format!("Bearer {}", config.api_key),
                );
            } else {
                builder = builder
                    .header("x-api-key", &config.api_key)
                    .header("anthropic-version", "2023-06-01");
            }
        } else if config.provider == "anthropic" {
            builder = builder.header("anthropic-version", "2023-06-01");
        }
        let mut response = if get {
            builder.send_empty()
        } else {
            builder.send_json(payload)
        }
        .map_err(|e| {
            error(
                format!(
                    "{provider} API request failed: {}",
                    if matches!(e, ureq::Error::Timeout(_)) {
                        "timed out".into()
                    } else {
                        agent_dump_core::output::render::safe_line(
                            &e.to_string(),
                        )
                    }
                ),
                true,
            )
        })?;
        let status = response.status().as_u16();
        if (matches!(status, 301..=303) || (get && matches!(status, 307 | 308)))
            && let Some(location) = response
                .headers()
                .get("location")
                .and_then(|s| s.to_str().ok())
        {
            if redirects == 10 {
                return Err(error(
                    format!("{provider} API HTTP {status}"),
                    false,
                ));
            }
            let next = url.join(location).map_err(|e| {
                error(format!("{provider} API request failed: {e}"), false)
            })?;
            if !matches!(next.scheme(), "http" | "https") {
                return Err(error(
                    format!("{provider} API HTTP {status}"),
                    false,
                ));
            }
            credentials &= next.origin() == origin;
            url = next;
            get = true;
            continue;
        }
        let successful = status < 400 && !matches!(status, 300..=399);
        let limit = if successful { 256 * 1024 } else { 4 * 1024 };
        let too_large = || {
            error(
                if successful {
                    format!("{provider} API response exceeded {limit} bytes")
                } else {
                    format!(
                        "{provider} API HTTP {status}: response body exceeded {limit} bytes"
                    )
                },
                false,
            )
        };
        if response
            .headers()
            .get("content-length")
            .and_then(|v| v.to_str().ok())
            .and_then(|s| s.parse::<u64>().ok())
            .is_some_and(|n| n > limit)
        {
            return Err(too_large());
        }
        let mut bytes = Vec::new();
        if let Err(e) = response
            .body_mut()
            .as_reader()
            .take(limit + 1)
            .read_to_end(&mut bytes)
        {
            return Err(if successful {
                error(
                    format!(
                        "{provider} API request failed: {}",
                        agent_dump_core::output::render::safe_line(
                            &e.to_string()
                        )
                    ),
                    true,
                )
            } else {
                error(
                    format!(
                        "{provider} API HTTP {status}: response body unavailable"
                    ),
                    status == 429 || (500..600).contains(&status),
                )
            });
        }
        if bytes.len() as u64 > limit {
            return Err(too_large());
        }
        if !successful {
            let mut failure = error(
                format!("{provider} API HTTP {status}"),
                status == 429 || (500..600).contains(&status),
            );
            if (400..500).contains(&status)
                && let Ok(data) = serde_json::from_slice::<Value>(&bytes)
            {
                let param = data["error"]["param"].as_str().unwrap_or("");
                let message = data["error"]["message"]
                    .as_str()
                    .unwrap_or("")
                    .to_lowercase();
                failure.rejected =
                    ["enable_thinking", "temperature", "max_tokens"]
                        .into_iter()
                        .find(|name| {
                            param == *name
                                || (message.contains(name)
                                    && [
                                        "unrecognized request argument",
                                        "unknown parameter",
                                        "unsupported parameter",
                                        "unexpected keyword argument",
                                        "extra inputs are not permitted",
                                    ]
                                    .iter()
                                    .any(|s| message.contains(s)))
                        });
            }
            return Err(failure);
        }
        return agent_dump_core::compat::json::from_slice(&bytes)
            .map_err(|e| error(e.to_string(), false));
    }
    unreachable!()
}

pub fn summary(
    config: &AiConfig,
    prompt: &str,
    timeout: u64,
    zh: bool,
) -> crate::Result<String> {
    let response = match respond(config, prompt, timeout, None) {
        Err(error) if error.retryable => {
            respond(config, prompt, timeout, None)?
        }
        result => result?,
    };
    let (provider, reason) = if config.provider == "openai" {
        (
            "OpenAI",
            (response["choices"][0]["finish_reason"] == "length")
                .then_some("finish_reason=length"),
        )
    } else {
        (
            "Anthropic",
            (response["stop_reason"] == "max_tokens")
                .then_some("stop_reason=max_tokens"),
        )
    };
    if let Some(reason) = reason {
        return Err(agent_dump_core::output::i18n::t(
            "LLM_RESPONSE_TRUNCATED",
            zh,
            &[("provider", provider.into()), ("reason", reason.into())],
        )
        .into());
    }
    Ok(content(config, &response)?)
}
