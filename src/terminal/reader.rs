use super::tui::{self, Row};
use agent_dump_core::{
    output::{i18n::t, render},
    session::SessionData,
};
use crossterm::{
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
    execute,
};
use ratatui::{
    Frame,
    layout::{Constraint, Layout, Rect},
    style::{Color, Modifier, Style},
    text::Line,
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph, Wrap},
};
use unicode_width::UnicodeWidthChar;

pub enum Action {
    Select,
    Export,
    Quit,
}

#[derive(Default)]
struct State {
    selected: usize,
    body_focus: bool,
    offset: usize,
    expanded: bool,
    query: String,
    editing: Option<String>,
    lines: Vec<String>,
    starts: Vec<usize>,
    hits: Vec<usize>,
    hit: usize,
}

pub struct Reader {
    terminal: ratatui::DefaultTerminal,
    _restore: tui::Restore,
    rows: Vec<Row>,
    state: State,
    zh: bool,
    pub status: String,
}

impl Reader {
    pub fn new(rows: Vec<Row>, zh: bool) -> crate::Result<Self> {
        let restore = tui::Restore;
        Ok(Self {
            terminal: tui::init()?,
            _restore: restore,
            rows,
            state: State::default(),
            zh,
            status: t("READER_READY", zh, &[]),
        })
    }

    pub const fn selected(&self) -> usize {
        self.state.selected
    }

    pub fn next(
        &mut self,
        data: Option<&SessionData>,
        error: Option<&str>,
    ) -> crate::Result<Action> {
        let mut dirty = true;
        let mut jump = None;
        loop {
            let size = self.terminal.size()?;
            let width = if size.width >= 90 {
                size.width - size.width / 3
            } else {
                size.width
            };
            if dirty {
                self.state.reflow(
                    data,
                    error,
                    usize::from(width.saturating_sub(2).max(1)),
                    self.zh,
                );
                dirty = false;
            }
            if let Some(message) = jump.take() {
                self.state.offset = self.state.hit_offset(message);
            }
            self.state.offset = self
                .state
                .offset
                .min(self.state.lines.len().saturating_sub(1));
            self.terminal.draw(|frame| {
                draw(frame, &self.rows, &self.state, &self.status, self.zh);
            })?;
            match event::read()? {
                Event::Resize(_, _) => {
                    dirty = true;
                }
                Event::Paste(text) => {
                    if let Some(input) = &mut self.state.editing {
                        input.push_str(&render::safe_body(&text));
                    }
                }
                Event::Key(key) if key.kind != KeyEventKind::Release => {
                    if key.code == KeyCode::Char('c')
                        && key.modifiers.contains(KeyModifiers::CONTROL)
                    {
                        return Ok(Action::Quit);
                    }
                    if let Some(input) = &mut self.state.editing {
                        match key.code {
                            KeyCode::Esc => self.state.editing = None,
                            KeyCode::Backspace => {
                                input.pop();
                            }
                            KeyCode::Char(c) if !c.is_control() => {
                                input.push(c);
                            }
                            KeyCode::Enter => {
                                self.state.query =
                                    self.state.editing.take().unwrap();
                                self.state.search(data);
                                self.state.expanded = true;
                                self.state.body_focus = true;
                                dirty = true;
                                jump = self.state.hits.first().copied();
                                self.status = t(
                                    "READER_MATCHES",
                                    self.zh,
                                    &[(
                                        "count",
                                        self.state.hits.len().to_string(),
                                    )],
                                );
                            }
                            _ => {}
                        }
                        continue;
                    }
                    let page =
                        usize::from(size.height.saturating_sub(7).max(1));
                    match key.code {
                        KeyCode::Esc | KeyCode::Char('q' | 'Q') => {
                            return Ok(Action::Quit);
                        }
                        KeyCode::Tab | KeyCode::BackTab => {
                            self.state.body_focus = !self.state.body_focus;
                        }
                        KeyCode::Enter | KeyCode::Right => {
                            self.state.body_focus = true;
                        }
                        KeyCode::Left => self.state.body_focus = false,
                        KeyCode::Char('/') => {
                            self.state.editing = Some(String::new());
                        }
                        KeyCode::Char('t') => {
                            self.state.expanded = !self.state.expanded;
                            dirty = true;
                        }
                        KeyCode::Char('e') if data.is_some() => {
                            return Ok(Action::Export);
                        }
                        KeyCode::Char('y') => {
                            self.status = match execute!(self.terminal.backend_mut(), crossterm::clipboard::CopyToClipboard::to_clipboard_from(&self.rows[self.state.selected].group)) {
                                Ok(()) => t("READER_COPY_REQUEST", self.zh, &[]),
                                Err(error) => render::safe_line(&error.to_string()),
                            };
                        }
                        KeyCode::Char('n' | 'N')
                            if !self.state.hits.is_empty() =>
                        {
                            let count = self.state.hits.len();
                            self.state.hit = if key.code == KeyCode::Char('N') {
                                (self.state.hit + count - 1) % count
                            } else {
                                (self.state.hit + 1) % count
                            };
                            jump = Some(self.state.hits[self.state.hit]);
                            self.state.body_focus = true;
                        }
                        KeyCode::Up | KeyCode::Char('k')
                            if self.state.body_focus =>
                        {
                            self.state.offset =
                                self.state.offset.saturating_sub(1);
                        }
                        KeyCode::Down | KeyCode::Char('j')
                            if self.state.body_focus =>
                        {
                            self.state.offset =
                                self.state.offset.saturating_add(1);
                        }
                        KeyCode::PageUp => {
                            self.state.body_focus = true;
                            self.state.offset =
                                self.state.offset.saturating_sub(page);
                        }
                        KeyCode::PageDown => {
                            self.state.body_focus = true;
                            self.state.offset =
                                self.state.offset.saturating_add(page);
                        }
                        KeyCode::Home if self.state.body_focus => {
                            self.state.offset = 0;
                        }
                        KeyCode::End if self.state.body_focus => {
                            self.state.offset =
                                self.state.lines.len().saturating_sub(page);
                        }
                        KeyCode::Up
                        | KeyCode::Char('k' | 'j')
                        | KeyCode::Down
                        | KeyCode::Home
                        | KeyCode::End => {
                            let selected = match key.code {
                                KeyCode::Up | KeyCode::Char('k') => {
                                    self.state.selected.saturating_sub(1)
                                }
                                KeyCode::Home => 0,
                                KeyCode::End => self.rows.len() - 1,
                                _ => (self.state.selected + 1)
                                    .min(self.rows.len() - 1),
                            };
                            if selected != self.state.selected {
                                self.state = State {
                                    selected,
                                    ..State::default()
                                };
                                self.status = t("READER_READY", self.zh, &[]);
                                return Ok(Action::Select);
                            }
                        }
                        _ => {}
                    }
                }
                _ => {}
            }
        }
    }
}

impl State {
    fn hit_offset(&self, message: usize) -> usize {
        let start = self.starts.get(message).copied().unwrap_or(0);
        let end = self
            .starts
            .get(message + 1)
            .copied()
            .unwrap_or(self.lines.len());
        let query = agent_dump_core::query::text::TextQuery::new(
            &self.query,
            agent_dump_core::query::text::Mode::Phrase,
        );
        let joined = self.lines[start..end].concat();
        let Some(span) = query.first_literal_span(&joined) else {
            return start;
        };
        let mut offset = 0;
        for index in start..end {
            offset += self.lines[index].len();
            if span.start < offset {
                return index;
            }
        }
        start
    }

    fn search(&mut self, data: Option<&SessionData>) {
        let query = agent_dump_core::query::text::TextQuery::new(
            &self.query,
            agent_dump_core::query::text::Mode::Phrase,
        );
        self.hits = data
            .into_iter()
            .flat_map(|data| data.messages.iter().enumerate())
            .filter_map(|(i, message)| {
                query
                    .find(&[
                        &agent_dump_core::query::transcript::searchable_message(
                            message,
                        ),
                    ])
                    .map(|_| i)
            })
            .collect();
        self.hit = 0;
    }

    fn reflow(
        &mut self,
        data: Option<&SessionData>,
        error: Option<&str>,
        width: usize,
        zh: bool,
    ) {
        self.lines.clear();
        self.starts.clear();
        if let Some(error) = error {
            self.lines = wrap(&render::safe_body(error), width);
        } else if let Some(data) = data {
            for (i, message) in data.messages.iter().enumerate() {
                self.starts.push(self.lines.len());
                self.lines.extend(wrap(
                    &format!("# {} · {}", i + 1, message.role),
                    width,
                ));
                self.lines.extend(wrap(
                    &render::reader_message(message, self.expanded),
                    width,
                ));
                self.lines.push(String::new());
            }
        }
        if self.lines.is_empty() {
            self.lines.push(t("READER_EMPTY_BODY", zh, &[]));
        }
    }
}

fn wrap(text: &str, width: usize) -> Vec<String> {
    let mut lines = Vec::new();
    for line in text.lines() {
        let mut current = String::new();
        let mut used = 0;
        for c in line.chars() {
            let size = c.width().unwrap_or(0);
            if used + size > width && !current.is_empty() {
                lines.push(std::mem::take(&mut current));
                used = 0;
            }
            current.push(c);
            used += size;
        }
        lines.push(current);
    }
    lines
}

fn draw(
    frame: &mut Frame<'_>,
    rows: &[Row],
    state: &State,
    status: &str,
    zh: bool,
) {
    let area = frame.area();
    if area.height < 7 || area.width < 20 {
        frame.render_widget(Paragraph::new(t("READER_SMALL", zh, &[])), area);
        return;
    }
    let areas = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(1),
        Constraint::Length(1),
        Constraint::Length(2),
    ])
    .split(area);
    frame.render_widget(
        Paragraph::new(render::safe_line(&rows[state.selected].group))
            .style(Style::default().add_modifier(Modifier::BOLD)),
        areas[0],
    );
    if area.width >= 90 {
        let panes = Layout::horizontal([
            Constraint::Length(area.width / 3),
            Constraint::Min(1),
        ])
        .split(areas[1]);
        draw_list(frame, panes[0], rows, state, zh);
        draw_body(frame, panes[1], state, zh);
    } else if state.body_focus {
        draw_body(frame, areas[1], state, zh);
    } else {
        draw_list(frame, areas[1], rows, state, zh);
    }
    let status = state.editing.as_ref().map_or_else(
        || render::safe_line(status),
        |input| format!("/{}", render::safe_line(input)),
    );
    frame.render_widget(
        Paragraph::new(status).style(Style::default().fg(Color::Yellow)),
        areas[2],
    );
    frame.render_widget(
        Paragraph::new(t(
            if area.width < 30 {
                "READER_HELP_TINY"
            } else if area.width < 70 {
                "READER_HELP_COMPACT"
            } else {
                "READER_HELP"
            },
            zh,
            &[],
        ))
        .wrap(Wrap { trim: false }),
        areas[3],
    );
}

fn draw_list(
    frame: &mut Frame<'_>,
    area: Rect,
    rows: &[Row],
    state: &State,
    zh: bool,
) {
    let items = rows
        .iter()
        .map(|row| {
            ListItem::new(vec![
                Line::raw(row.title.clone()),
                Line::styled(
                    row.detail.clone(),
                    Style::default().fg(Color::DarkGray),
                ),
            ])
        })
        .collect::<Vec<_>>();
    frame.render_stateful_widget(
        List::new(items)
            .block(panel(t("READER_SESSIONS", zh, &[]), !state.body_focus))
            .highlight_symbol("› ")
            .highlight_style(Style::default().add_modifier(Modifier::REVERSED)),
        area,
        &mut ListState::default().with_selected(Some(state.selected)),
    );
}

fn draw_body(frame: &mut Frame<'_>, area: Rect, state: &State, zh: bool) {
    let height = usize::from(area.height.saturating_sub(2));
    let active = state.hits.get(state.hit).map(|&hit| state.hit_offset(hit));
    let lines = state
        .lines
        .iter()
        .enumerate()
        .skip(state.offset)
        .take(height)
        .map(|(i, line)| {
            let style = if active == Some(i) {
                Style::default()
                    .fg(Color::Yellow)
                    .add_modifier(Modifier::BOLD)
            } else if line.starts_with("# ") {
                Style::default()
                    .fg(Color::Cyan)
                    .add_modifier(Modifier::BOLD)
            } else {
                Style::default()
            };
            Line::styled(line.clone(), style)
        })
        .collect::<Vec<_>>();
    let title = format!(
        "{} · {}/{}",
        t("READER_BODY", zh, &[]),
        state.offset + 1,
        state.lines.len()
    );
    frame.render_widget(
        Paragraph::new(lines).block(panel(title, state.body_focus)),
        area,
    );
}

fn panel(title: String, focused: bool) -> Block<'static> {
    Block::default()
        .borders(Borders::ALL)
        .title(title)
        .border_style(Style::default().fg(if focused {
            Color::Cyan
        } else {
            Color::DarkGray
        }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use agent_dump_core::session::{
        Message, Part, Session, Stats, timestamp::Timestamp,
    };
    use ratatui::{Terminal, backend::TestBackend};

    #[test]
    #[ignore = "Manual release benchmark; see docs/benchmarks/reader-redraw.md"]
    fn benchmark_reader_redraw() {
        use std::hash::{DefaultHasher, Hash, Hasher};
        use std::time::Instant;

        for (name, chars, row_count) in [
            ("small", 128, 1),
            ("many-sessions", 128, 1000),
            ("large-message", 8 * 1024 * 1024, 1),
        ] {
            let session = Session::new(
                "benchmark".into(),
                "Reader benchmark".into(),
                std::path::PathBuf::new(),
                Timestamp::UNIX_EPOCH,
                Timestamp::UNIX_EPOCH,
            );
            let data = session.payload(
                vec![Message::new(
                    "message".into(),
                    "assistant",
                    0,
                    vec![Part::text(
                        format!("{}\nneedle", "x".repeat(chars)),
                        0,
                    )],
                )],
                Stats::default(),
            );
            let rows = (0..row_count)
                .map(|i| Row {
                    title: format!("Reader benchmark session {i}"),
                    detail: "Codex · 2026-10-02 12:00".into(),
                    group: format!("codex://benchmark-{i}"),
                })
                .collect::<Vec<_>>();
            let mut state = State {
                body_focus: true,
                expanded: true,
                query: "needle".into(),
                ..State::default()
            };
            state.search(Some(&data));
            assert_eq!(state.hits, vec![0]);
            state.reflow(Some(&data), None, 65, false);
            state.offset = state.hit_offset(0);
            let mut terminal =
                Terminal::new(TestBackend::new(100, 24)).unwrap();
            for _ in 0..5 {
                terminal
                    .draw(|frame| {
                        draw(frame, &rows, &state, "benchmark", false);
                    })
                    .unwrap();
            }
            let iterations = 200;
            let start = Instant::now();
            for _ in 0..iterations {
                terminal
                    .draw(|frame| {
                        draw(frame, &rows, &state, "benchmark", false);
                    })
                    .unwrap();
            }
            let elapsed = start.elapsed().as_secs_f64();
            let screen = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(ratatui::buffer::Cell::symbol)
                .collect::<String>();
            assert!(screen.contains("needle"));
            let mut digest = DefaultHasher::new();
            format!("{:?}", terminal.backend().buffer()).hash(&mut digest);
            println!(
                "REDRAW_BENCH {}",
                serde_json::json!({
                    "name": name, "chars": chars, "rows": row_count,
                    "iterations": iterations, "elapsed_seconds": elapsed,
                    "screen_hash": format!("{:016x}", digest.finish())
                })
            );
        }
    }

    #[test]
    fn reader_renders_wide_narrow_and_searches_tool_content() {
        let session = Session::new(
            "fixture".into(),
            "数据库锁排查".into(),
            std::path::PathBuf::new(),
            Timestamp::UNIX_EPOCH,
            Timestamp::UNIX_EPOCH,
        );
        let data = session.payload(vec![
            Message::new("one".into(), "user", 0, vec![Part::text("导出遇到数据库锁。请检查原因。".into(), 0)]),
            Message::new("two".into(), "assistant", 0, vec![Part::tool("exec", "call", serde_json::json!({"input": "hidden-needle", "output": "completed"}), 0)]),
        ], Stats::default());
        let rows = vec![Row {
            title: session.title,
            detail: "Codex · 09-29 16:00".into(),
            group: "codex://fixture".into(),
        }];
        let mut state = State::default();
        state.reflow(Some(&data), None, 60, true);
        assert!(
            !state
                .lines
                .iter()
                .any(|line| line.contains("hidden-needle"))
        );
        state.query = "hidden-needle".into();
        state.search(Some(&data));
        assert_eq!(state.hits, vec![1]);
        state.expanded = true;
        for (width, height, body_focus) in
            [(100, 20, false), (40, 12, true), (20, 7, true)]
        {
            state.body_focus = body_focus;
            state.reflow(
                Some(&data),
                None,
                if width >= 90 {
                    usize::from(width - width / 3 - 2)
                } else {
                    usize::from(width - 2)
                },
                true,
            );
            let mut terminal =
                Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal
                .draw(|frame| draw(frame, &rows, &state, "测试状态", true))
                .unwrap();
            let screen = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(ratatui::buffer::Cell::symbol)
                .collect::<String>();
            assert!(screen.contains("正") && screen.contains("文"));
            assert!(screen.contains("codex://fixture"));
            println!("\n{width}x{height}");
            for row in terminal
                .backend()
                .buffer()
                .content
                .chunks(usize::from(width))
            {
                println!(
                    "{}",
                    row.iter()
                        .map(ratatui::buffer::Cell::symbol)
                        .collect::<String>()
                );
            }
        }
        assert!(state.hit_offset(1) > state.starts[1]);
        assert!(
            state.lines[state.hit_offset(1)..]
                .concat()
                .contains("hidden-needle")
        );
    }
}
