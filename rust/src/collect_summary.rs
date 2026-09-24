use crate::collect_log::Logger;
use crate::collect_model::{Mode, Summary};
use crate::config::AiConfig;
use serde_json::{Value, json};
use std::collections::HashSet;

pub fn normalize(payload: &Value, mode: Mode) -> crate::Result<Summary> {
    let fields = mode.fields();
    let object = payload
        .as_object()
        .filter(|object| {
            !object.is_empty() && object.keys().all(|key| fields.contains(&key.as_str()))
        })
        .ok_or("summary must contain only recognized fields and cannot be an empty object")?;
    for (key, value) in object {
        if !value
            .as_array()
            .is_some_and(|array| array.iter().all(Value::is_string))
        {
            return Err(format!("summary field {key} must be an array of strings").into());
        }
    }
    let mut result = Summary::new();
    for field in fields {
        let items = object
            .get(field)
            .and_then(Value::as_array)
            .map_or(&[][..], Vec::as_slice);
        result.insert(
            field.into(),
            dedupe(items.iter().filter_map(Value::as_str), Some(12)).into(),
        );
    }
    Ok(result)
}

fn dedupe<'a>(items: impl Iterator<Item = &'a str>, limit: Option<usize>) -> Vec<Value> {
    let mut seen = HashSet::new();
    let mut values = Vec::new();
    for text in items {
        let text = crate::query_text::normalize(text);
        if text.is_empty() || !seen.insert(caseless::default_case_fold_str(&text)) {
            continue;
        }
        values.push(text.into());
        if limit.is_some_and(|limit| values.len() >= limit) {
            break;
        }
    }
    values
}

pub fn merge(payloads: &[Summary], mode: Mode) -> Summary {
    mode.fields()
        .into_iter()
        .map(|field| {
            let values = payloads
                .iter()
                .filter_map(|p| p[field].as_array())
                .flatten()
                .filter_map(Value::as_str);
            (field.into(), Value::Array(dedupe(values, None)))
        })
        .collect()
}

pub fn needs_compression(payload: &Summary) -> bool {
    payload
        .values()
        .filter_map(Value::as_array)
        .any(|v| v.len() > 12)
        || payload
            .values()
            .filter_map(Value::as_array)
            .map(Vec::len)
            .sum::<usize>()
            > 48
}

fn extract(response: &str) -> crate::Result<Value> {
    use std::sync::LazyLock;
    static FENCE: LazyLock<regex::Regex> =
        LazyLock::new(|| regex::Regex::new(r"(?i)```json\s*(\{[\s\S]*?\})\s*```").unwrap());
    let mut candidates = Vec::new();
    if let Some(found) = FENCE.captures(response) {
        candidates.push(found.get(1).unwrap().as_str());
    }
    candidates.push(response.trim());
    if let (Some(start), Some(end)) = (response.find('{'), response.rfind('}'))
        && end > start
    {
        candidates.push(&response[start..=end]);
    }
    let mut errors = Vec::new();
    let mut seen = HashSet::new();
    for text in candidates {
        if text.is_empty() {
            continue;
        }
        let parsed = serde_json::Deserializer::from_str(text.trim())
            .into_iter::<Value>()
            .next();
        match parsed {
            Some(Ok(value)) if value.is_object() => return Ok(value),
            Some(Ok(_)) => {}
            _ => {
                if let Err(error) = crate::python_json::from_slice(text.trim().as_bytes()) {
                    let message = error.to_string();
                    if let Some((reason, location)) = message.rsplit_once(": line ") {
                        let detail = format!(
                            "{reason} at line {} of {}",
                            location.replace(" (char ", " char ").trim_end_matches(')'),
                            text.chars().count()
                        );
                        if seen.insert(detail.clone()) && errors.len() < 3 {
                            errors.push(detail);
                        }
                    }
                }
            }
        }
    }
    Err(if errors.is_empty() {
        "response is not valid JSON object".to_owned()
    } else {
        format!("response is not valid JSON object: {}", errors.join("; "))
    }
    .into())
}

pub struct Context<'a> {
    pub label: String,
    pub phase: &'static str,
    pub uri: Option<&'a str>,
    pub chunk: Option<usize>,
    pub chunks: Option<usize>,
}

pub fn request(
    config: &AiConfig,
    prompt: &str,
    timeout: u64,
    mode: Mode,
    context: Context<'_>,
    logger: &Logger,
) -> crate::Result<Summary> {
    let mut current = prompt.to_owned();
    let mut parse_attempt = 0;
    let mut transport_attempt = 0;
    loop {
        let id = uuid::Uuid::new_v4().to_string();
        let mut fields = json!({"request_id":id, "provider":config.provider, "model":config.model, "phase":context.phase, "context":context.label,
            "session_uri":context.uri, "chunk_index":context.chunk, "chunk_total":context.chunks,
            "parse_attempt":parse_attempt + 1, "parse_attempt_limit":2, "transport_attempt":transport_attempt + 1, "transport_attempt_limit":2});
        fields["prompt_chars"] = current.chars().count().into();
        logger.log("llm_request", fields.clone());
        fields.as_object_mut().unwrap().remove("prompt_chars");
        let response = match crate::llm::request(config, &current, timeout, Some(mode)) {
            Ok(response) => response,
            Err(error) => {
                let retry = error.retryable && transport_attempt < 1;
                fields["error"] = error.to_string().into();
                fields["retryable"] = error.retryable.into();
                fields["will_retry"] = retry.into();
                fields["retry_kind"] = if retry {
                    "transport".into()
                } else {
                    Value::Null
                };
                logger.log("llm_request_error", fields);
                if retry {
                    transport_attempt += 1;
                    continue;
                }
                return Err(format!(
                    "{}: structured summary request failed: {error}",
                    context.label
                )
                .into());
            }
        };
        fields["response_chars"] = response.chars().count().into();
        logger.log("llm_response", fields.clone());
        match extract(&response).and_then(|v| normalize(&v, mode)) {
            Ok(summary) => return Ok(summary),
            Err(error) => {
                let retry = parse_attempt < 1;
                fields["error"] = error.to_string().into();
                fields["will_retry"] = retry.into();
                fields["retry_kind"] = if retry {
                    "parse_correction".into()
                } else {
                    Value::Null
                };
                fields["response_preview"] = crate::collect_prompts::preview(&response, 400).into();
                let normalized = response.trim();
                fields["response_tail_preview"] = if normalized.chars().count() > 400 {
                    format!(
                        "...{}",
                        normalized
                            .chars()
                            .skip(normalized.chars().count() - 397)
                            .collect::<String>()
                            .trim_start()
                    )
                } else {
                    normalized.into()
                }
                .into();
                logger.log("llm_parse_error", fields);
                if !retry {
                    return Err(format!(
                        "{}: invalid structured summary response: {error}",
                        context.label
                    )
                    .into());
                }
                parse_attempt += 1;
                transport_attempt = 0;
                current = crate::collect_prompts::retry(
                    prompt,
                    &response,
                    mode,
                    &format!("{}://request/{id}", context.phase),
                );
            }
        }
    }
}
