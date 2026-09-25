use std::fmt;

#[derive(Debug)]
pub struct Error {
    pub kind: &'static str,
    pub(super) message: String,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}
impl std::error::Error for Error {}
pub fn invalid_utf8(bytes: &[u8], error: std::str::Utf8Error) -> Error {
    let start = error.valid_up_to();
    let end = error
        .error_len()
        .map_or(bytes.len(), |length| start + length);
    let reason = if error.error_len().is_none() {
        "unexpected end of data"
    } else if matches!(bytes[start], 0xc2..=0xf4) {
        "invalid continuation byte"
    } else {
        "invalid start byte"
    };
    let evidence = if end == start + 1 {
        format!("byte 0x{:02x} in position {start}", bytes[start])
    } else {
        format!("bytes in position {start}-{}", end - 1)
    };
    Error {
        kind: "UnicodeDecodeError",
        message: format!("'utf-8' codec can't decode {evidence}: {reason}"),
    }
}

pub fn syntax(text: &str, original: &serde_json::Error) -> Error {
    let mut parser = Parser {
        chars: text.chars().collect(),
        index: 0,
    };
    let failure = if text.starts_with('\u{feff}') {
        Some(("Unexpected UTF-8 BOM (decode using utf-8-sig)", 0))
    } else {
        parser.value().err().or_else(|| {
            parser.whitespace();
            (parser.index < parser.chars.len())
                .then_some(("Extra data", parser.index))
        })
    };
    let message = if let Some((message, position)) = failure {
        let before = &parser.chars[..position];
        let line = before.iter().filter(|c| **c == '\n').count() + 1;
        let column = position
            - before
                .iter()
                .rposition(|c| *c == '\n')
                .map_or(0, |index| index + 1)
            + 1;
        format!("{message}: line {line} column {column} (char {position})")
    } else {
        original.to_string()
    };
    Error {
        kind: "JSONDecodeError",
        message,
    }
}

type Failure = (&'static str, usize);

struct Parser {
    chars: Vec<char>,
    index: usize,
}

impl Parser {
    fn whitespace(&mut self) {
        while self
            .chars
            .get(self.index)
            .is_some_and(|c| matches!(c, ' ' | '\r' | '\n' | '\t'))
        {
            self.index += 1;
        }
    }

    fn consume(&mut self, expected: char) -> bool {
        if self.chars.get(self.index) == Some(&expected) {
            self.index += 1;
            true
        } else {
            false
        }
    }

    fn value(&mut self) -> Result<(), Failure> {
        static NUMBER: std::sync::LazyLock<regex::Regex> =
            std::sync::LazyLock::new(|| {
                regex::Regex::new(
                    r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?",
                )
                .unwrap()
            });

        self.whitespace();
        match self.chars.get(self.index).copied() {
            Some('"') => self.string(),
            Some('{') => self.object(),
            Some('[') => self.array(),
            _ => {
                for word in
                    ["null", "true", "false", "NaN", "Infinity", "-Infinity"]
                {
                    if self.chars[self.index..]
                        .iter()
                        .take(word.len())
                        .copied()
                        .eq(word.chars())
                    {
                        self.index += word.len();
                        return Ok(());
                    }
                }
                let rest: String = self.chars[self.index..]
                    .iter()
                    .copied()
                    .take_while(|character| {
                        character.is_ascii_digit()
                            || matches!(character, '-' | '+' | '.' | 'e' | 'E')
                    })
                    .collect();
                if let Some(number) = NUMBER.find(&rest) {
                    self.index += number.len();
                    Ok(())
                } else {
                    Err(("Expecting value", self.index))
                }
            }
        }
    }

    fn string(&mut self) -> Result<(), Failure> {
        let start = self.index;
        self.index += 1;
        while let Some(character) = self.chars.get(self.index).copied() {
            self.index += 1;
            match character {
                '"' => return Ok(()),
                '\\' => {
                    let Some(escape) = self.chars.get(self.index).copied()
                    else {
                        break;
                    };
                    self.index += 1;
                    if escape == 'u' {
                        if self
                            .chars
                            .get(self.index..self.index + 4)
                            .is_none_or(|chars| {
                                !chars.iter().all(char::is_ascii_hexdigit)
                            })
                        {
                            return Err((
                                "Invalid \\uXXXX escape",
                                self.index - 1,
                            ));
                        }
                        self.index += 4;
                    } else if !matches!(
                        escape,
                        '"' | '\\' | '/' | 'b' | 'f' | 'n' | 'r' | 't'
                    ) {
                        return Err(("Invalid \\escape", self.index - 2));
                    }
                }
                character if character < ' ' => {
                    return Err((
                        "Invalid control character at",
                        self.index - 1,
                    ));
                }
                _ => {}
            }
        }
        Err(("Unterminated string starting at", start))
    }

    fn object(&mut self) -> Result<(), Failure> {
        self.index += 1;
        self.whitespace();
        if self.consume('}') {
            return Ok(());
        }
        loop {
            self.whitespace();
            if self.chars.get(self.index) != Some(&'"') {
                return Err((
                    "Expecting property name enclosed in double quotes",
                    self.index,
                ));
            }
            self.string()?;
            self.whitespace();
            if !self.consume(':') {
                return Err(("Expecting ':' delimiter", self.index));
            }
            self.value()?;
            self.whitespace();
            if self.consume('}') {
                return Ok(());
            }
            if !self.consume(',') {
                return Err(("Expecting ',' delimiter", self.index));
            }
        }
    }

    fn array(&mut self) -> Result<(), Failure> {
        self.index += 1;
        self.whitespace();
        if self.consume(']') {
            return Ok(());
        }
        loop {
            self.value()?;
            self.whitespace();
            if self.consume(']') {
                return Ok(());
            }
            if !self.consume(',') {
                return Err(("Expecting ',' delimiter", self.index));
            }
        }
    }
}
