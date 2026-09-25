use serde_json::{Value, json};

struct Hunk<'a> {
    header: Option<&'a str>,
    lines: Vec<(char, &'a str)>,
}

struct Operation<'a> {
    action: &'static str,
    path: &'a str,
    old_path: Option<&'a str>,
    hunks: Vec<Hunk<'a>>,
}

pub fn parse(raw: &str, zh: bool) -> Value {
    let mut result = json!({"kind": "apply_patch", "raw": raw, "content": []});
    match content(raw, zh) {
        Ok(blocks) => result["content"] = blocks.into(),
        Err(error) => result["parse_error"] = error.into(),
    }
    result
}

fn content(raw: &str, zh: bool) -> Result<Vec<Value>, String> {
    let normalized = raw.replace("\r\n", "\n");
    let lines: Vec<_> = normalized
        .split_terminator([
            '\n', '\r', '\u{b}', '\u{c}', '\u{1c}', '\u{1d}', '\u{1e}',
            '\u{85}', '\u{2028}', '\u{2029}',
        ])
        .collect();
    if lines.is_empty() {
        return Err(if zh { "patch 为空" } else { "patch is empty" }.into());
    }
    if lines[0] != "*** Begin Patch" {
        return Err(if zh {
            "patch 缺少 Begin Patch 头"
        } else {
            "patch is missing the Begin Patch header"
        }
        .into());
    }
    let mut index = 1;
    let mut blocks = Vec::new();
    while index < lines.len() {
        let line = lines[index];
        if line == "*** End Patch" {
            return Ok(blocks);
        }
        let (action, path) =
            if let Some(path) = line.strip_prefix("*** Add File: ") {
                ("add", path)
            } else if let Some(path) = line.strip_prefix("*** Delete File: ") {
                ("delete", path)
            } else if let Some(path) = line.strip_prefix("*** Update File: ") {
                ("update", path)
            } else {
                return Err(format!(
                    "{}: {line}",
                    if zh {
                        "无法解析 patch 操作头"
                    } else {
                        "cannot parse patch operation header"
                    }
                ));
            };
        index += 1;
        let mut operation = Operation {
            action,
            path,
            old_path: None,
            hunks: Vec::new(),
        };
        if action == "update"
            && let Some(path) = lines
                .get(index)
                .and_then(|line| line.strip_prefix("*** Move to: "))
        {
            if path != operation.path {
                operation.old_path = Some(operation.path);
                operation.path = path;
                operation.action = "move";
            }
            index += 1;
        }
        let mut header = None;
        while let Some(line) = lines.get(index) {
            if [
                "*** Add File: ",
                "*** Delete File: ",
                "*** Update File: ",
                "*** End Patch",
            ]
            .iter()
            .any(|prefix| line.starts_with(prefix))
            {
                break;
            }
            index += 1;
            if *line == "*** End of File" {
                continue;
            }
            if line.starts_with("@@") {
                header = Some(*line);
                if operation
                    .hunks
                    .last()
                    .is_none_or(|hunk| hunk.header != header)
                {
                    operation.hunks.push(Hunk {
                        header,
                        lines: Vec::new(),
                    });
                }
                continue;
            }
            let Some(kind @ ('+' | '-' | ' ')) = line.chars().next() else {
                return Err(format!(
                    "{}: {line}",
                    if zh {
                        "无法解析 patch 行"
                    } else {
                        "cannot parse patch line"
                    }
                ));
            };
            if operation
                .hunks
                .last()
                .is_none_or(|hunk| hunk.header != header)
            {
                operation.hunks.push(Hunk {
                    header,
                    lines: Vec::new(),
                });
            }
            operation
                .hunks
                .last_mut()
                .unwrap()
                .lines
                .push((kind, &line[1..]));
        }
        if operation.old_path.is_some() && !operation.hunks.is_empty() {
            operation.action = "update";
        }
        blocks.push(block(operation));
    }
    Err(if zh {
        "patch 缺少 End Patch 尾"
    } else {
        "patch is missing the End Patch footer"
    }
    .into())
}

fn block(operation: Operation<'_>) -> Value {
    let (kind, content) = match operation.action {
        "add" => (
            "write_file",
            operation
                .hunks
                .iter()
                .flat_map(|hunk| &hunk.lines)
                .filter(|(kind, _)| *kind != '-')
                .map(|(_, text)| *text)
                .collect::<Vec<_>>()
                .join("\n"),
        ),
        "delete" => ("delete_file", String::new()),
        "move" => ("move_file", String::new()),
        _ => {
            let mut lines = vec![
                format!("Index: {}", operation.path),
                "=".repeat(67),
                format!("--- {}", operation.old_path.unwrap_or(operation.path)),
                format!("+++ {}", operation.path),
            ];
            for hunk in operation.hunks {
                if let Some(header) = hunk.header {
                    lines.push(header.into());
                }
                for (kind, text) in hunk.lines {
                    lines.push(format!("{kind}{text}"));
                }
            }
            ("edit_file", lines.join("\n"))
        }
    };
    json!({"type": kind, "path": operation.path, "old_path": operation.old_path, "input": {"content": content}})
}
