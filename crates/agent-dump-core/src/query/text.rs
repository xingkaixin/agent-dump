use regex::{Regex, RegexBuilder};

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Phrase,
    Terms,
}

pub struct TextQuery {
    pub mode: Mode,
    pub literals: Vec<String>,
    patterns: Vec<Regex>,
}

pub struct Evidence {
    pub snippet: String,
    pub title_matches: bool,
}
pub fn whitespace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

pub fn normalize(text: &str) -> String {
    text.split(whitespace)
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

impl TextQuery {
    pub fn new(raw: &str, mode: Mode) -> Self {
        let normalized = normalize(raw);
        let mut literals = Vec::new();
        if !normalized.is_empty() {
            if mode == Mode::Phrase {
                literals.push(normalized);
            } else {
                for term in normalized.split(' ') {
                    if !literals.iter().any(|s| s == term) {
                        literals.push(term.to_owned());
                    }
                }
            }
        }
        let patterns = literals
            .iter()
            .map(|literal| {
                // Python IGNORECASE includes dotted and dotless I in the same class.
                let pattern = literal
                    .chars()
                    .map(|c| match c {
                        'i' | 'I' | 'İ' | 'ı' => "[iIİı]".into(),
                        _ => regex::escape(&c.to_string()),
                    })
                    .collect::<String>();
                RegexBuilder::new(&pattern)
                    .case_insensitive(true)
                    .size_limit(usize::MAX)
                    .build()
                    .unwrap()
            })
            .collect();
        Self {
            mode,
            literals,
            patterns,
        }
    }
    pub fn find(&self, fields: &[&str]) -> Option<Evidence> {
        if self.patterns.is_empty() {
            return None;
        }
        let fields: Vec<_> = fields.iter().map(|s| normalize(s)).collect();
        let spans: Vec<Vec<_>> = fields
            .iter()
            .map(|s| self.patterns.iter().map(|p| p.find(s)).collect())
            .collect();
        if !(0..self.patterns.len())
            .all(|term| spans.iter().any(|field| field[term].is_some()))
        {
            return None;
        }
        let title_matches = spans
            .first()
            .is_some_and(|field| field.iter().all(Option::is_some));
        let mut ranked: Vec<_> = (0..fields.len()).collect();
        ranked.sort_by_key(|&i| {
            std::cmp::Reverse(spans[i].iter().filter(|s| s.is_some()).count())
        });
        for term in 0..self.patterns.len() {
            for &i in &ranked {
                if let Some(span) = spans[i][term] {
                    let text = &fields[i];
                    let before = &text[..span.start()];
                    let after = &text[span.end()..];
                    let start = before
                        .char_indices()
                        .rev()
                        .nth(47)
                        .map_or(0, |(i, _)| i);
                    let end = after
                        .char_indices()
                        .nth(48)
                        .map_or(after.len(), |(i, _)| i);
                    return Some(Evidence {
                        snippet: format!(
                            "{}{}**{}**{}{}",
                            if start > 0 { "..." } else { "" },
                            &before[start..],
                            span.as_str(),
                            &after[..end],
                            if end < after.len() { "..." } else { "" }
                        ),
                        title_matches,
                    });
                }
            }
        }
        None
    }
    pub fn has_evidence(&self, snippet: &str) -> bool {
        let normalized = normalize(&snippet.replace("**", ""));
        self.patterns
            .iter()
            .any(|pattern| pattern.is_match(&normalized))
    }
}
