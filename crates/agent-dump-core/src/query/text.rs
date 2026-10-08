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
    let mut normalized = String::with_capacity(text.len());
    for word in text.split(whitespace).filter(|s| !s.is_empty()) {
        if !normalized.is_empty() {
            normalized.push(' ');
        }
        normalized.push_str(word);
    }
    normalized
}

/// Normalizes the first 48 characters away from a match, which borders the
/// text on the side the characters start from. Also reports whether more
/// normalized text follows.
fn window(chars: impl Iterator<Item = char>) -> (String, bool) {
    let mut text = String::new();
    let mut count = 0;
    let mut gap = false;
    for c in chars {
        if whitespace(c) {
            gap = true;
            continue;
        }
        for c in gap.then_some(' ').into_iter().chain([c]) {
            if count == 48 {
                return (text, true);
            }
            text.push(c);
            count += 1;
        }
        gap = false;
    }
    (text, false)
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
        // Literals without spaces never span whitespace, so they match the
        // raw text exactly where they match its normalized form.
        if self.literals.iter().any(|literal| literal.contains(' ')) {
            let normalized: Vec<_> =
                fields.iter().map(|s| normalize(s)).collect();
            let normalized: Vec<_> =
                normalized.iter().map(String::as_str).collect();
            return self.evidence(&normalized);
        }
        self.evidence(fields)
    }
    fn evidence(&self, fields: &[&str]) -> Option<Evidence> {
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
                    let text = fields[i];
                    let (before, earlier) =
                        window(text[..span.start()].chars().rev());
                    let (after, later) = window(text[span.end()..].chars());
                    return Some(Evidence {
                        snippet: format!(
                            "{}{}**{}**{}{}",
                            if earlier { "..." } else { "" },
                            before.chars().rev().collect::<String>(),
                            span.as_str(),
                            after,
                            if later { "..." } else { "" }
                        ),
                        title_matches,
                    });
                }
            }
        }
        None
    }
    pub fn first_literal_span(
        &self,
        text: &str,
    ) -> Option<std::ops::Range<usize>> {
        self.patterns
            .iter()
            .filter_map(|pattern| pattern.find(text))
            .min_by_key(regex::Match::start)
            .map(|matched| matched.range())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snippets_read_raw_text_as_normalized_text() {
        let text = format!(
            "  \t{}\u{3000}\u{3000}needle\n\n{}  ",
            "w ".repeat(30),
            "x".repeat(47)
        );
        let snippet = |query: &str, mode| {
            TextQuery::new(query, mode)
                .find(&["", &text])
                .unwrap()
                .snippet
        };
        assert_eq!(
            snippet("NEEDLE", Mode::Terms),
            format!("...{}**needle** {}", "w ".repeat(24), "x".repeat(47))
        );
        assert_eq!(
            snippet("w needle", Mode::Phrase),
            format!("...{}**w needle** {}", "w ".repeat(24), "x".repeat(47))
        );
    }
}
