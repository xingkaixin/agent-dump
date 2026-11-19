use std::collections::HashMap;
use std::sync::OnceLock;
pub fn terminal(key: &str, zh: bool, values: &[(&str, String)]) -> String {
    t(
        key,
        zh,
        &values
            .iter()
            .map(|(key, value)| (*key, crate::output::render::safe_line(value)))
            .collect::<Vec<_>>(),
    )
}

pub fn t(key: &str, zh: bool, values: &[(&str, String)]) -> String {
    static EN: OnceLock<HashMap<String, String>> = OnceLock::new();
    static ZH: OnceLock<HashMap<String, String>> = OnceLock::new();
    let catalog = if zh {
        ZH.get_or_init(|| {
            serde_json::from_str(include_str!(
                "../../../../resources/locales/zh.json"
            ))
            .unwrap()
        })
    } else {
        EN.get_or_init(|| {
            serde_json::from_str(include_str!(
                "../../../../resources/locales/en.json"
            ))
            .unwrap()
        })
    };
    let template = &catalog[key];
    let mut output = String::new();
    let mut rest = template.as_str();
    while let Some(start) = rest.find('{') {
        output.push_str(&rest[..start]);
        let Some(end) = rest[start..].find('}').map(|end| start + end) else {
            output.push_str(&rest[start..]);
            return output;
        };
        let field = &rest[start + 1..end];
        if let Some((_, value)) = values.iter().find(|(key, _)| *key == field) {
            output.push_str(value);
        } else {
            output.push_str(&rest[start..=end]);
        }
        rest = &rest[end + 1..];
    }
    output.push_str(rest);
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::de::{self, Deserialize, Deserializer, MapAccess, Visitor};
    use std::collections::{BTreeMap, BTreeSet};
    use std::fmt;
    use std::path::{Path, PathBuf};

    const EN_JSON: &str = include_str!("../../../../resources/locales/en.json");
    const ZH_JSON: &str = include_str!("../../../../resources/locales/zh.json");

    struct UniqueLocaleMap(BTreeMap<String, String>);

    impl<'de> Deserialize<'de> for UniqueLocaleMap {
        fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
        where
            D: Deserializer<'de>,
        {
            struct LocaleVisitor;

            impl<'de> Visitor<'de> for LocaleVisitor {
                type Value = UniqueLocaleMap;

                fn expecting(
                    &self,
                    formatter: &mut fmt::Formatter<'_>,
                ) -> fmt::Result {
                    formatter.write_str(
                        "a JSON object mapping locale keys to strings",
                    )
                }

                fn visit_map<A>(
                    self,
                    mut access: A,
                ) -> Result<Self::Value, A::Error>
                where
                    A: MapAccess<'de>,
                {
                    let mut map = BTreeMap::new();
                    while let Some((key, value)) =
                        access.next_entry::<String, String>()?
                    {
                        if map.insert(key.clone(), value).is_some() {
                            return Err(de::Error::custom(format!(
                                "duplicate locale key: {key}"
                            )));
                        }
                    }
                    Ok(UniqueLocaleMap(map))
                }
            }

            deserializer.deserialize_map(LocaleVisitor)
        }
    }

    fn parse_locale_strict(raw: &str, name: &str) -> BTreeMap<String, String> {
        serde_json::from_str::<UniqueLocaleMap>(raw)
            .unwrap_or_else(|error| panic!("failed to parse {name}: {error}"))
            .0
    }

    fn extract_placeholders(
        template: &str,
    ) -> Result<BTreeSet<String>, String> {
        let mut placeholders = BTreeSet::new();
        let mut current: Option<String> = None;
        for ch in template.chars() {
            match ch {
                '{' => {
                    if current.is_some() {
                        return Err("nested opening brace '{'".into());
                    }
                    current = Some(String::new());
                }
                '}' => {
                    let Some(name) = current.take() else {
                        return Err("stray closing brace '}'".into());
                    };
                    if name.is_empty()
                        || !name
                            .bytes()
                            .all(|b| b.is_ascii_alphanumeric() || b == b'_')
                    {
                        return Err(format!(
                            "invalid placeholder '{{{name}}}'"
                        ));
                    }
                    placeholders.insert(name);
                }
                other => {
                    if let Some(name) = &mut current {
                        name.push(other);
                    }
                }
            }
        }
        if let Some(unclosed) = current {
            return Err(format!("unclosed placeholder '{{{unclosed}'"));
        }
        Ok(placeholders)
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum Token {
        Ident(String),
        Str(String),
        Punct(char),
    }

    fn skip_raw_string(source: &str, start: usize) -> Option<(usize, String)> {
        let bytes = source.as_bytes();
        let mut i = start;
        let mut hashes = 0usize;
        while bytes.get(i) == Some(&b'#') {
            hashes += 1;
            i += 1;
        }
        if bytes.get(i) != Some(&b'"') {
            return None;
        }
        i += 1;
        let content_start = i;
        while i < bytes.len() {
            if bytes[i] == b'"' {
                let mut matched = 0;
                while matched < hashes
                    && bytes.get(i + 1 + matched) == Some(&b'#')
                {
                    matched += 1;
                }
                if matched == hashes {
                    let content = source[content_start..i].to_owned();
                    return Some((i + 1 + hashes, content));
                }
            }
            i += 1;
        }
        None
    }

    fn scan_quoted_string(source: &str, quote_pos: usize) -> (usize, String) {
        let bytes = source.as_bytes();
        let mut i = quote_pos + 1;
        let mut out = String::new();
        while i < bytes.len() {
            match bytes[i] {
                b'"' => return (i + 1, out),
                b'\\' => {
                    i += 1;
                    if i >= bytes.len() {
                        break;
                    }
                    match bytes[i] {
                        b'n' => {
                            out.push('\n');
                            i += 1;
                        }
                        b'r' => {
                            out.push('\r');
                            i += 1;
                        }
                        b't' => {
                            out.push('\t');
                            i += 1;
                        }
                        b'0' => {
                            out.push('\0');
                            i += 1;
                        }
                        b'\\' => {
                            out.push('\\');
                            i += 1;
                        }
                        b'"' => {
                            out.push('"');
                            i += 1;
                        }
                        b'\'' => {
                            out.push('\'');
                            i += 1;
                        }
                        b'\n' => {
                            i += 1;
                            while i < bytes.len()
                                && bytes[i].is_ascii_whitespace()
                            {
                                i += 1;
                            }
                        }
                        b'\r' if bytes.get(i + 1) == Some(&b'\n') => {
                            i += 2;
                            while i < bytes.len()
                                && bytes[i].is_ascii_whitespace()
                            {
                                i += 1;
                            }
                        }
                        other => {
                            out.push(other as char);
                            i += 1;
                        }
                    }
                }
                _ => {
                    let ch = source[i..].chars().next().unwrap();
                    out.push(ch);
                    i += ch.len_utf8();
                }
            }
        }
        (i, out)
    }

    fn skip_comment(bytes: &[u8], i: usize) -> Option<usize> {
        if bytes[i] != b'/' {
            return None;
        }
        if bytes.get(i + 1) == Some(&b'/') {
            let mut j = i + 2;
            while j < bytes.len() && bytes[j] != b'\n' {
                j += 1;
            }
            return Some(j);
        }
        if bytes.get(i + 1) == Some(&b'*') {
            let mut j = i + 2;
            let mut depth = 1usize;
            while j + 1 < bytes.len() && depth > 0 {
                if bytes[j] == b'/' && bytes[j + 1] == b'*' {
                    depth += 1;
                    j += 2;
                } else if bytes[j] == b'*' && bytes[j + 1] == b'/' {
                    depth -= 1;
                    j += 2;
                } else {
                    j += 1;
                }
            }
            return Some(j);
        }
        None
    }

    fn skip_prefixed_literal(source: &str, i: usize) -> Option<usize> {
        let bytes = source.as_bytes();
        let b = bytes[i];
        if !matches!(b, b'b' | b'c') {
            return None;
        }
        if bytes.get(i + 1) == Some(&b'r')
            && let Some((next, _)) = skip_raw_string(source, i + 2)
        {
            return Some(next);
        }
        if bytes.get(i + 1) == Some(&b'"') {
            return Some(scan_quoted_string(source, i + 1).0);
        }
        if b == b'b' && bytes.get(i + 1) == Some(&b'\'') {
            return skip_char_literal(source, i + 1);
        }
        None
    }

    fn skip_char_literal(source: &str, i: usize) -> Option<usize> {
        let bytes = source.as_bytes();
        if bytes.get(i) != Some(&b'\'') {
            return None;
        }
        if bytes.get(i + 1) == Some(&b'\\') {
            let mut j = i + 2;
            while j < bytes.len() && bytes[j] != b'\'' {
                j += 1;
            }
            return Some((j + 1).min(bytes.len()));
        }
        let ch = source[i + 1..].chars().next()?;
        let close = i + 1 + ch.len_utf8();
        (bytes.get(close) == Some(&b'\'')).then_some(close + 1)
    }

    fn tokenize_rust(source: &str) -> Vec<Token> {
        let bytes = source.as_bytes();
        let mut tokens = Vec::new();
        let mut i = 0;
        while i < bytes.len() {
            let b = bytes[i];
            if b.is_ascii_whitespace() {
                i += 1;
            } else if let Some(next) = skip_comment(bytes, i) {
                i = next;
            } else if b == b'r'
                && let Some((next, value)) = skip_raw_string(source, i + 1)
            {
                tokens.push(Token::Str(value));
                i = next;
            } else if let Some(next) = skip_prefixed_literal(source, i) {
                i = next;
            } else if b == b'"' {
                let (next, value) = scan_quoted_string(source, i);
                tokens.push(Token::Str(value));
                i = next;
            } else if let Some(next) = skip_char_literal(source, i) {
                i = next;
            } else if b.is_ascii_alphabetic() || b == b'_' {
                let start = i;
                i += 1;
                while i < bytes.len()
                    && (bytes[i].is_ascii_alphanumeric() || bytes[i] == b'_')
                {
                    i += 1;
                }
                tokens.push(Token::Ident(source[start..i].to_owned()));
            } else if b.is_ascii() {
                tokens.push(Token::Punct(b as char));
                i += 1;
            } else {
                i += source[i..].chars().next().unwrap().len_utf8();
            }
        }
        tokens
    }

    fn matching_delim(
        tokens: &[Token],
        open_idx: usize,
        open: char,
        close: char,
    ) -> Option<usize> {
        let mut depth = 0usize;
        for (idx, token) in tokens.iter().enumerate().skip(open_idx) {
            if *token == Token::Punct(open) {
                depth += 1;
            } else if *token == Token::Punct(close) {
                depth = depth.checked_sub(1)?;
                if depth == 0 {
                    return Some(idx);
                }
            }
        }
        None
    }

    fn is_cfg_test(tokens: &[Token], i: usize) -> bool {
        matches!(
            tokens.get(i..i + 7),
            Some(
                [
                    Token::Punct('#'),
                    Token::Punct('['),
                    Token::Ident(cfg),
                    Token::Punct('('),
                    Token::Ident(test),
                    Token::Punct(')'),
                    Token::Punct(']'),
                ]
            ) if cfg == "cfg" && test == "test"
        )
    }

    fn strip_cfg_test(tokens: &[Token]) -> Vec<Token> {
        let mut out = Vec::with_capacity(tokens.len());
        let mut i = 0;
        while i < tokens.len() {
            if is_cfg_test(tokens, i) {
                i += 7;
                while i + 1 < tokens.len()
                    && tokens[i] == Token::Punct('#')
                    && tokens[i + 1] == Token::Punct('[')
                {
                    if let Some(end) = matching_delim(tokens, i + 1, '[', ']') {
                        i = end + 1;
                    } else {
                        return out;
                    }
                }
                let mut paren_depth = 0usize;
                let mut bracket_depth = 0usize;
                while i < tokens.len() {
                    match tokens[i] {
                        Token::Punct('(') => paren_depth += 1,
                        Token::Punct(')') => {
                            paren_depth = paren_depth.saturating_sub(1);
                        }
                        Token::Punct('[') => bracket_depth += 1,
                        Token::Punct(']') => {
                            bracket_depth = bracket_depth.saturating_sub(1);
                        }
                        Token::Punct('{')
                            if paren_depth == 0 && bracket_depth == 0 =>
                        {
                            if let Some(end) =
                                matching_delim(tokens, i, '{', '}')
                            {
                                i = end + 1;
                            } else {
                                return out;
                            }
                            break;
                        }
                        Token::Punct(';')
                            if paren_depth == 0 && bracket_depth == 0 =>
                        {
                            i += 1;
                            break;
                        }
                        _ => {}
                    }
                    i += 1;
                }
                continue;
            }
            out.push(tokens[i].clone());
            i += 1;
        }
        out
    }

    fn split_top_level(tokens: &[Token], sep: char) -> Vec<&[Token]> {
        let mut parts = Vec::new();
        let mut start = 0;
        let mut paren = 0usize;
        let mut bracket = 0usize;
        let mut brace = 0usize;
        for (i, token) in tokens.iter().enumerate() {
            match token {
                Token::Punct('(') => paren += 1,
                Token::Punct(')') => paren = paren.saturating_sub(1),
                Token::Punct('[') => bracket += 1,
                Token::Punct(']') => bracket = bracket.saturating_sub(1),
                Token::Punct('{') => brace += 1,
                Token::Punct('}') => brace = brace.saturating_sub(1),
                Token::Punct(c)
                    if *c == sep
                        && paren == 0
                        && bracket == 0
                        && brace == 0 =>
                {
                    parts.push(&tokens[start..i]);
                    start = i + 1;
                }
                _ => {}
            }
        }
        if start < tokens.len() {
            parts.push(&tokens[start..]);
        }
        parts
    }

    fn extract_expr_strings(expr: &[Token], out: &mut Vec<String>) {
        if let [Token::Str(value)] = expr {
            out.push(value.clone());
            return;
        }
        if let [
            Token::Ident(some),
            Token::Punct('('),
            Token::Str(value),
            Token::Punct(')'),
        ] = expr
            && some == "Some"
        {
            out.push(value.clone());
            return;
        }
        if matches!(expr.first(), Some(Token::Ident(kw)) if kw == "if") {
            let mut i = 0;
            let mut paren = 0usize;
            while i < expr.len() {
                match &expr[i] {
                    Token::Punct('(') => paren += 1,
                    Token::Punct(')') => paren = paren.saturating_sub(1),
                    Token::Punct('{') if paren == 0 => {
                        if let Some(end) = matching_delim(expr, i, '{', '}') {
                            extract_expr_strings(&expr[i + 1..end], out);
                            i = end + 1;
                            continue;
                        }
                    }
                    _ => {}
                }
                i += 1;
            }
            return;
        }
        if matches!(expr.first(), Some(Token::Ident(kw)) if kw == "match")
            && let Some(open) =
                expr.iter().position(|t| *t == Token::Punct('{'))
            && let Some(close) = matching_delim(expr, open, '{', '}')
        {
            let body = &expr[open + 1..close];
            for arm in split_top_level(body, ',') {
                if let Some(arrow) = arm.windows(2).position(|pair| {
                    pair == [Token::Punct('='), Token::Punct('>')]
                }) {
                    extract_expr_strings(&arm[arrow + 2..], out);
                }
            }
            return;
        }
        if matches!(expr.first(), Some(Token::Punct('{')))
            && let Some(end) = matching_delim(expr, 0, '{', '}')
            && end + 1 == expr.len()
        {
            extract_expr_strings(&expr[1..end], out);
        }
    }

    fn extract_branch_all_strings(expr: &[Token], out: &mut Vec<String>) {
        let mut i = 0;
        let mut paren = 0usize;
        while i < expr.len() {
            match &expr[i] {
                Token::Punct('(') => paren += 1,
                Token::Punct(')') => paren = paren.saturating_sub(1),
                Token::Punct('{') if paren == 0 => {
                    if let Some(end) = matching_delim(expr, i, '{', '}') {
                        for token in &expr[i + 1..end] {
                            if let Token::Str(value) = token {
                                out.push(value.clone());
                            }
                        }
                        i = end + 1;
                        continue;
                    }
                }
                _ => {}
            }
            i += 1;
        }
    }

    fn extract_fn_body<'a>(
        tokens: &'a [Token],
        name: &str,
    ) -> Option<&'a [Token]> {
        for i in 0..tokens.len().saturating_sub(2) {
            if matches!(
                (&tokens[i], &tokens[i + 1]),
                (Token::Ident(fn_kw), Token::Ident(fn_name))
                if fn_kw == "fn" && fn_name == name
            ) {
                let mut paren = 0usize;
                for (j, token) in tokens.iter().enumerate().skip(i + 2) {
                    match token {
                        Token::Punct('(') => paren += 1,
                        Token::Punct(')') => paren = paren.saturating_sub(1),
                        Token::Punct('{') if paren == 0 => {
                            let close = matching_delim(tokens, j, '{', '}')?;
                            return Some(&tokens[j + 1..close]);
                        }
                        Token::Punct(';') if paren == 0 => break,
                        _ => {}
                    }
                }
            }
        }
        None
    }

    fn extract_let_rhs<'a>(
        tokens: &'a [Token],
        binding_idents: &[&str],
    ) -> Vec<&'a [Token]> {
        let mut results = Vec::new();
        let mut i = 0;
        while i < tokens.len() {
            if matches!(&tokens[i], Token::Ident(kw) if kw == "let") {
                let mut j = i + 1;
                let mut idents = Vec::new();
                while j < tokens.len() && tokens[j] != Token::Punct('=') {
                    if let Token::Ident(ident) = &tokens[j] {
                        idents.push(ident.as_str());
                    }
                    if matches!(tokens[j], Token::Punct(';' | '{')) {
                        break;
                    }
                    j += 1;
                }
                if j < tokens.len()
                    && tokens[j] == Token::Punct('=')
                    && tokens.get(j + 1) != Some(&Token::Punct('='))
                    && idents.as_slice() == binding_idents
                {
                    let rhs_start = j + 1;
                    let mut paren = 0usize;
                    let mut bracket = 0usize;
                    let mut brace = 0usize;
                    let mut k = rhs_start;
                    while k < tokens.len() {
                        match tokens[k] {
                            Token::Punct('(') => paren += 1,
                            Token::Punct(')') => {
                                paren = paren.saturating_sub(1);
                            }
                            Token::Punct('[') => bracket += 1,
                            Token::Punct(']') => {
                                bracket = bracket.saturating_sub(1);
                            }
                            Token::Punct('{') => brace += 1,
                            Token::Punct('}') => {
                                brace = brace.saturating_sub(1);
                            }
                            Token::Punct(';')
                                if paren == 0 && bracket == 0 && brace == 0 =>
                            {
                                results.push(&tokens[rhs_start..k]);
                                i = k + 1;
                                break;
                            }
                            _ => {}
                        }
                        k += 1;
                    }
                    if k < tokens.len() {
                        continue;
                    }
                }
            }
            i += 1;
        }
        results
    }

    fn extract_for_in_arrays<'a>(
        tokens: &'a [Token],
        pat_idents: &[&str],
    ) -> Vec<&'a [Token]> {
        let mut arrays = Vec::new();
        let mut i = 0;
        while i < tokens.len() {
            if matches!(&tokens[i], Token::Ident(kw) if kw == "for") {
                let mut j = i + 1;
                let mut idents = Vec::new();
                while j < tokens.len() {
                    if matches!(&tokens[j], Token::Ident(kw) if kw == "in") {
                        break;
                    }
                    if let Token::Ident(ident) = &tokens[j] {
                        idents.push(ident.as_str());
                    }
                    j += 1;
                }
                if j + 1 < tokens.len()
                    && idents.as_slice() == pat_idents
                    && tokens[j + 1] == Token::Punct('[')
                    && let Some(close) = matching_delim(tokens, j + 1, '[', ']')
                {
                    arrays.push(&tokens[j + 2..close]);
                    i = close + 1;
                    continue;
                }
            }
            i += 1;
        }
        arrays
    }

    fn extract_array_strings(
        inner: &[Token],
        tuple_index: Option<usize>,
        out: &mut Vec<String>,
    ) {
        for element in split_top_level(inner, ',') {
            if element.is_empty() {
                continue;
            }
            if let Some(index) = tuple_index {
                if element.first() == Some(&Token::Punct('('))
                    && let Some(close) = matching_delim(element, 0, '(', ')')
                    && close + 1 == element.len()
                {
                    let fields = split_top_level(&element[1..close], ',');
                    if let Some(field) = fields.get(index) {
                        extract_expr_strings(field, out);
                    }
                }
            } else {
                extract_expr_strings(element, out);
            }
        }
    }

    fn extract_call_arg_strings(
        tokens: &[Token],
        callee: &str,
        expected_arity: usize,
        arg_index: usize,
        out: &mut Vec<String>,
    ) {
        for i in 0..tokens.len().saturating_sub(1) {
            if matches!(&tokens[i], Token::Ident(name) if name == callee)
                && tokens[i + 1] == Token::Punct('(')
            {
                let prev = i.checked_sub(1).and_then(|idx| tokens.get(idx));
                if matches!(prev, Some(Token::Punct('.')))
                    || matches!(prev, Some(Token::Ident(kw)) if kw == "fn")
                {
                    continue;
                }
                if let Some(close) = matching_delim(tokens, i + 1, '(', ')') {
                    let args = split_top_level(&tokens[i + 2..close], ',');
                    if args.len() == expected_arity {
                        extract_expr_strings(args[arg_index], out);
                    }
                }
            }
        }
    }

    fn extract_some_strings(tokens: &[Token], out: &mut Vec<String>) {
        for i in 0..tokens.len().saturating_sub(3) {
            if let [
                Token::Ident(some),
                Token::Punct('('),
                Token::Str(value),
                Token::Punct(')'),
            ] = &tokens[i..i + 4]
                && some == "Some"
            {
                out.push(value.clone());
            }
        }
    }

    fn require_keys(
        label: &str,
        keys: &mut Vec<String>,
        extract: impl FnOnce(&mut Vec<String>),
    ) {
        let before = keys.len();
        extract(keys);
        assert!(keys.len() > before, "failed to extract keys from {label}");
    }

    fn extract_for_table(
        tokens: &[Token],
        pat_idents: &[&str],
        tuple_index: Option<usize>,
        out: &mut Vec<String>,
    ) {
        for array in extract_for_in_arrays(tokens, pat_idents) {
            extract_array_strings(array, tuple_index, out);
        }
    }

    fn extract_command_keys(tokens: &[Token], keys: &mut Vec<String>) {
        for fn_name in ["stderr_error", "plan_error"] {
            let body = extract_fn_body(tokens, fn_name).unwrap_or_else(|| {
                panic!("src/command.rs should define fn {fn_name}")
            });
            require_keys(&format!("src/command.rs::{fn_name}"), keys, |out| {
                extract_some_strings(body, out);
            });
        }
        let warn_body = extract_fn_body(tokens, "warn_ignored")
            .expect("src/command.rs should define fn warn_ignored");
        require_keys("src/command.rs::warn_ignored", keys, |out| {
            extract_for_table(warn_body, &["present", "key"], Some(1), out);
        });
    }

    fn extract_collect_keys(tokens: &[Token], keys: &mut Vec<String>) {
        require_keys("src/workflows/collect.rs::fail", keys, |out| {
            extract_call_arg_strings(tokens, "fail", 6, 2, out);
        });
        let body = extract_fn_body(tokens, "dry_run")
            .expect("workflows/collect.rs should define fn dry_run");
        let open = body
            .iter()
            .position(|t| *t == Token::Punct('['))
            .expect("dry_run should contain array literal");
        let close = matching_delim(body, open, '[', ']')
            .expect("dry_run array should close");
        require_keys("src/workflows/collect.rs::dry_run", keys, |out| {
            extract_array_strings(&body[open + 1..close], Some(0), out);
        });
    }

    fn extract_config_workflow_keys(tokens: &[Token], keys: &mut Vec<String>) {
        let fields_body = extract_fn_body(tokens, "fields")
            .expect("workflows/config.rs should define fn fields");
        require_keys("src/workflows/config.rs::fields", keys, |out| {
            extract_for_table(
                fields_body,
                &["key", "field", "value"],
                Some(0),
                out,
            );
        });
        let prompt_body = extract_fn_body(tokens, "prompt")
            .expect("workflows/config.rs should define fn prompt");
        require_keys("src/workflows/config.rs::prompt", keys, |out| {
            extract_for_table(
                prompt_body,
                &["key", "secret", "default"],
                Some(0),
                out,
            );
        });
    }

    fn extract_known_table_keys(
        rel_path: &str,
        tokens: &[Token],
        keys: &mut Vec<String>,
    ) {
        match rel_path {
            "src/cli_args.rs" => {
                let body = extract_fn_body(tokens, "command")
                    .expect("src/cli_args.rs should define fn command");
                let mut suffixes = Vec::new();
                extract_for_table(body, &["id", "key"], Some(1), &mut suffixes);
                assert!(
                    !suffixes.is_empty(),
                    "failed to extract CLI_*_HELP table from src/cli_args.rs"
                );
                keys.extend(
                    suffixes.into_iter().map(|s| format!("CLI_{s}_HELP")),
                );
            }
            "src/command.rs" => extract_command_keys(tokens, keys),
            "crates/agent-dump-core/src/output/diagnostics.rs" => {
                let body = extract_fn_body(tokens, "query_error")
                    .expect("diagnostics.rs should define fn query_error");
                require_keys("diagnostics.rs::query_error", keys, |out| {
                    for rhs in extract_let_rhs(body, &["summary", "steps"]) {
                        extract_branch_all_strings(rhs, out);
                    }
                });
            }
            "crates/agent-dump-core/src/config.rs" => {
                let body = extract_fn_body(tokens, "collect_ai_error")
                    .expect("config.rs should define fn collect_ai_error");
                require_keys("config.rs::collect_ai_error", keys, |out| {
                    for rhs in extract_let_rhs(body, &["key"]) {
                        extract_expr_strings(rhs, out);
                    }
                });
            }
            "crates/agent-dump-core/src/query/mod.rs" => {
                require_keys("query/mod.rs::error", keys, |out| {
                    extract_call_arg_strings(tokens, "error", 2, 0, out);
                });
            }
            "src/workflows/collect.rs" => extract_collect_keys(tokens, keys),
            "src/workflows/config.rs" => {
                extract_config_workflow_keys(tokens, keys);
            }
            "src/workflows/list.rs" => {
                require_keys("list.rs (present, key)", keys, |out| {
                    extract_for_table(
                        tokens,
                        &["present", "key"],
                        Some(1),
                        out,
                    );
                });
                require_keys("list.rs (key, value)", keys, |out| {
                    extract_for_table(tokens, &["key", "value"], Some(0), out);
                });
            }
            "src/workflows/maintenance.rs" => {
                require_keys("src/workflows/maintenance.rs", keys, |out| {
                    extract_for_table(tokens, &["key", "count"], None, out);
                });
            }
            "src/workflows/uri.rs" => {
                require_keys("src/workflows/uri.rs", keys, |out| {
                    for rhs in extract_let_rhs(tokens, &["key"]) {
                        extract_expr_strings(rhs, out);
                    }
                });
            }
            "src/terminal/selector.rs" => {
                let body = extract_fn_body(tokens, "sessions")
                    .expect("terminal/selector.rs should define fn sessions");
                require_keys("terminal/selector.rs::sessions", keys, |out| {
                    for rhs in extract_let_rhs(body, &["keys"]) {
                        if rhs.first() == Some(&Token::Punct('['))
                            && let Some(close) =
                                matching_delim(rhs, 0, '[', ']')
                        {
                            extract_array_strings(&rhs[1..close], None, out);
                        }
                    }
                });
            }
            "src/terminal/reader.rs" => {
                let body = extract_fn_body(tokens, "draw_status")
                    .expect("terminal/reader.rs should define fn draw_status");
                require_keys("terminal/reader.rs::draw_status", keys, |out| {
                    for rhs in extract_let_rhs(body, &["mode"]) {
                        extract_expr_strings(rhs, out);
                    }
                });
            }
            _ => {}
        }
    }

    fn extract_file_keys(rel_path: &str, tokens: &[Token]) -> Vec<String> {
        let mut keys = Vec::new();
        let has_i18n = tokens
            .iter()
            .any(|t| matches!(t, Token::Ident(id) if id == "i18n"));
        let has_progress = tokens
            .iter()
            .any(|t| matches!(t, Token::Ident(id) if id == "progress"));

        if has_i18n {
            extract_call_arg_strings(tokens, "t", 3, 0, &mut keys);
            extract_call_arg_strings(tokens, "terminal", 3, 0, &mut keys);
        }
        if has_progress {
            extract_call_arg_strings(tokens, "progress", 4, 0, &mut keys);
        }
        extract_known_table_keys(rel_path, tokens, &mut keys);
        keys
    }

    fn workspace_rust_files() -> Vec<(String, PathBuf)> {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(Path::parent)
            .expect("agent-dump-core should live under crates/agent-dump-core");
        let mut files = Vec::new();
        for dir in ["src", "crates/agent-dump-core/src"] {
            for entry in walkdir::WalkDir::new(root.join(dir)) {
                let entry = entry.expect("walkdir entry should be readable");
                let path = entry.path();
                if !entry.file_type().is_file()
                    || path.extension().and_then(|ext| ext.to_str())
                        != Some("rs")
                    || path.file_name().and_then(|name| name.to_str())
                        == Some("tests.rs")
                {
                    continue;
                }
                let rel = path
                    .strip_prefix(root)
                    .expect("source file should be inside workspace root")
                    .to_string_lossy()
                    .replace('\\', "/");
                files.push((rel, path.to_path_buf()));
            }
        }
        files.sort_by(|a, b| a.0.cmp(&b.0));
        files
    }

    #[test]
    fn locale_catalogs_have_identical_keys_without_duplicates() {
        let en = parse_locale_strict(EN_JSON, "en.json");
        let zh = parse_locale_strict(ZH_JSON, "zh.json");
        assert!(!en.is_empty(), "en.json must not be empty");
        let en_keys: BTreeSet<&str> = en.keys().map(String::as_str).collect();
        let zh_keys: BTreeSet<&str> = zh.keys().map(String::as_str).collect();
        let only_in_en: Vec<&str> =
            en_keys.difference(&zh_keys).copied().collect();
        let only_in_zh: Vec<&str> =
            zh_keys.difference(&en_keys).copied().collect();
        assert!(
            only_in_en.is_empty() && only_in_zh.is_empty(),
            "locale key mismatch:\n  only in en.json: {only_in_en:?}\n  only in zh.json: {only_in_zh:?}"
        );
        for (key, en_value) in &en {
            assert_eq!(t(key, false, &[]), *en_value);
            assert_eq!(t(key, true, &[]), zh[key]);
        }
    }

    #[test]
    fn locale_values_are_non_empty() {
        let mut empty = Vec::new();
        for (name, catalog) in [
            ("en.json", parse_locale_strict(EN_JSON, "en.json")),
            ("zh.json", parse_locale_strict(ZH_JSON, "zh.json")),
        ] {
            for (key, value) in catalog {
                if value.trim().is_empty() {
                    empty.push(format!("{name}:{key}"));
                }
            }
        }
        assert!(empty.is_empty(), "empty locale values found: {empty:?}");
    }

    #[test]
    fn locale_placeholders_match_and_are_well_formed() {
        let en = parse_locale_strict(EN_JSON, "en.json");
        let zh = parse_locale_strict(ZH_JSON, "zh.json");
        let mut malformed = Vec::new();
        let mut mismatched = Vec::new();
        for (key, en_value) in &en {
            let en_ph = match extract_placeholders(en_value) {
                Ok(ph) => Some(ph),
                Err(error) => {
                    malformed.push(format!("en.json:{key}: {error}"));
                    None
                }
            };
            let zh_ph = match zh.get(key) {
                Some(zh_value) => match extract_placeholders(zh_value) {
                    Ok(ph) => Some(ph),
                    Err(error) => {
                        malformed.push(format!("zh.json:{key}: {error}"));
                        None
                    }
                },
                None => None,
            };
            if let (Some(en_ph), Some(zh_ph)) = (en_ph, zh_ph)
                && en_ph != zh_ph
            {
                mismatched.push(format!("{key}: en={en_ph:?}, zh={zh_ph:?}"));
            }
        }
        assert!(
            malformed.is_empty(),
            "malformed placeholders found:\n{}",
            malformed.join("\n")
        );
        assert!(
            mismatched.is_empty(),
            "placeholder mismatch between en.json and zh.json:\n{}",
            mismatched.join("\n")
        );
    }

    #[test]
    fn referenced_locale_keys_exist_in_both_catalogs() {
        let en = parse_locale_strict(EN_JSON, "en.json");
        let zh = parse_locale_strict(ZH_JSON, "zh.json");
        let mut referenced: BTreeMap<String, BTreeSet<String>> =
            BTreeMap::new();

        for (rel_path, full_path) in workspace_rust_files() {
            let source =
                std::fs::read_to_string(&full_path).unwrap_or_else(|error| {
                    panic!("failed to read {rel_path}: {error}")
                });
            let tokens = strip_cfg_test(&tokenize_rust(&source));
            for key in extract_file_keys(&rel_path, &tokens) {
                referenced.entry(key).or_default().insert(rel_path.clone());
            }
        }

        assert!(
            referenced.len() >= 250,
            "expected workspace scan to find at least 250 locale keys, found {}",
            referenced.len()
        );
        for required in [
            "CLI_DESC",
            "CLI_URI_HELP",
            "READ_MODE_ERROR",
            "COLLECT_MODE_CONFLICT",
            "COLLECT_DRY_RUN_HEADER",
            "DIAG_QUERY_URI_INVALID",
            "QUERY_ERROR_EMPTY_SPEC",
            "READER_MODE_BROWSE",
        ] {
            assert!(
                referenced.contains_key(required),
                "expected scanner to discover {required}"
            );
        }

        let mut missing = Vec::new();
        for (key, files) in &referenced {
            let in_en = en.contains_key(key);
            let in_zh = zh.contains_key(key);
            if !in_en || !in_zh {
                let locales = match (in_en, in_zh) {
                    (false, false) => "en.json, zh.json",
                    (false, true) => "en.json",
                    (true, false) => "zh.json",
                    (true, true) => unreachable!(),
                };
                missing.push(format!(
                    "{key} (missing from {locales}; referenced in {:?})",
                    files.iter().collect::<Vec<_>>()
                ));
            }
        }
        assert!(
            missing.is_empty(),
            "referenced locale keys missing from catalogs:\n{}",
            missing.join("\n")
        );
    }
}
