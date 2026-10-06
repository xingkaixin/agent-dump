use super::tui::{self, Row};
use agent_dump_core::{
    output::{i18n::t, render},
    query::{
        Query, context,
        text::{Mode, TextQuery},
    },
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
    Export {
        locator: Option<String>,
        context: usize,
    },
    ExportMarked(Vec<usize>),
    Search(String),
    Quit,
}

#[derive(Clone, Copy)]
enum InputScope {
    Sessions,
    Messages,
}

#[derive(Default)]
struct State {
    selected: usize,
    body_focus: bool,
    offset: usize,
    expanded: bool,
    query: Query,
    editing: Option<(InputScope, String)>,
    context: Option<usize>,
    help: Option<u16>,
    lines: Vec<String>,
    starts: Vec<usize>,
    hits: Vec<usize>,
    hit: usize,
    active_hit_line: Option<usize>,
    marked: std::collections::BTreeSet<usize>,
}

pub struct Reader {
    terminal: ratatui::DefaultTerminal,
    _restore: tui::Restore,
    rows: Vec<Row>,
    query: Query,
    scope: String,
    state: State,
    zh: bool,
    pub status: String,
}

impl Reader {
    pub fn new(
        rows: Vec<Row>,
        query: &Query,
        scope: String,
        zh: bool,
    ) -> crate::Result<Self> {
        let restore = tui::Restore;
        Ok(Self {
            terminal: tui::init()?,
            _restore: restore,
            rows,
            state: State::with_query(query, 0),
            query: query.clone(),
            scope,
            zh,
            status: t("READER_READY", zh, &[]),
        })
    }

    pub fn set_results(&mut self, rows: Vec<Row>, query: &Query) {
        self.rows = rows;
        self.query = query.clone();
        self.state = State::with_query(query, 0);
    }

    fn render(&mut self) -> crate::Result<()> {
        self.terminal.draw(|frame| {
            draw(
                frame,
                &self.rows,
                &self.state,
                &self.status,
                &self.scope,
                &self.query,
                self.zh,
            );
        })?;
        Ok(())
    }

    pub const fn selected(&self) -> usize {
        self.state.selected
    }

    const fn scroll_help(&mut self, key: KeyCode, height: u16) {
        let offset = self.state.help.as_mut().unwrap();
        match key {
            KeyCode::Esc | KeyCode::Char('?' | 'q') => self.state.help = None,
            KeyCode::Up | KeyCode::Char('k') => {
                *offset = offset.saturating_sub(1);
            }
            KeyCode::Down | KeyCode::Char('j') => {
                *offset = offset.saturating_add(1);
            }
            KeyCode::PageUp => {
                *offset = offset.saturating_sub(height.saturating_sub(2));
            }
            KeyCode::PageDown => {
                *offset = offset.saturating_add(height.saturating_sub(2));
            }
            KeyCode::Home => *offset = 0,
            _ => {}
        }
    }

    fn toggle_excerpt(&mut self) {
        if self.state.context.is_some() {
            self.state.context = None;
            self.status = t("READER_READY", self.zh, &[]);
        } else if !self.state.hits.is_empty() {
            self.state.context = Some(3);
            self.state.body_focus = true;
            self.status = t("READER_EXCERPT_HELP", self.zh, &[]);
        } else {
            self.status = t("READER_NEED_HIT", self.zh, &[]);
        }
    }

    fn edit(
        &mut self,
        key: KeyCode,
        data: Option<&SessionData>,
    ) -> crate::Result<Option<Action>> {
        match key {
            KeyCode::Esc => self.state.editing = None,
            KeyCode::Backspace => {
                self.state.editing.as_mut().unwrap().1.pop();
            }
            KeyCode::Char(c) if !c.is_control() => {
                self.state.editing.as_mut().unwrap().1.push(c);
            }
            KeyCode::Enter => {
                let (scope, input) = self.state.editing.take().unwrap();
                if matches!(scope, InputScope::Sessions) {
                    self.status = t("READER_SEARCHING", self.zh, &[]);
                    self.render()?;
                    return Ok(Some(Action::Search(input)));
                }
                self.state.query = Query {
                    keyword: Some(input),
                    ..Query::default()
                };
                self.state.context = None;
                self.state.search(data)?;
                self.state.expanded = true;
                self.state.body_focus = true;
                self.status = t(
                    "READER_MATCHES",
                    self.zh,
                    &[("count", self.state.hits.len().to_string())],
                );
            }
            _ => {}
        }
        Ok(None)
    }

    pub fn next(
        &mut self,
        data: Option<&SessionData>,
        error: Option<&str>,
    ) -> crate::Result<Action> {
        let previous_hit = self.state.hit;
        self.state.search(data)?;
        self.state.hit =
            previous_hit.min(self.state.hits.len().saturating_sub(1));
        let mut dirty = true;
        let mut jump =
            self.state.lines.is_empty() && !self.state.hits.is_empty();
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
            if jump {
                self.state.offset = self.state.active_hit_line.unwrap_or(0);
                jump = false;
            }
            self.state.offset = self
                .state
                .offset
                .min(self.state.lines.len().saturating_sub(1));
            self.render()?;
            match event::read()? {
                Event::Resize(_, _) => {
                    dirty = true;
                }
                Event::Paste(text) => {
                    if let Some((_, input)) = &mut self.state.editing {
                        input.push_str(&render::safe_body(&text));
                    }
                }
                Event::Key(key) if key.kind != KeyEventKind::Release => {
                    if key.code == KeyCode::Char('c')
                        && key.modifiers.contains(KeyModifiers::CONTROL)
                    {
                        return Ok(Action::Quit);
                    }
                    if self.state.help.is_some() {
                        self.scroll_help(key.code, size.height);
                        continue;
                    }
                    if self.state.editing.is_some() {
                        if let Some(action) = self.edit(key.code, data)? {
                            return Ok(action);
                        }
                        if key.code == KeyCode::Enter {
                            dirty = true;
                            jump = !self.state.hits.is_empty();
                        }
                        continue;
                    }
                    let page =
                        usize::from(size.height.saturating_sub(7).max(1));
                    match key.code {
                        KeyCode::Esc if self.state.context.is_some() => {
                            self.state.context = None;
                            self.status = t("READER_READY", self.zh, &[]);
                            dirty = true;
                            jump = true;
                        }
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
                            self.state.editing =
                                Some((InputScope::Messages, String::new()));
                        }
                        KeyCode::Char('s') => {
                            self.state.editing =
                                Some((InputScope::Sessions, String::new()));
                        }
                        KeyCode::Char('c') => {
                            return Ok(Action::Search(String::new()));
                        }
                        KeyCode::Char('?') => self.state.help = Some(0),
                        KeyCode::Char('x') => {
                            self.toggle_excerpt();
                            dirty = true;
                            jump = true;
                        }
                        KeyCode::Char('+' | '=' | '-')
                            if self.state.context.is_some() =>
                        {
                            let radius = self.state.context.unwrap();
                            self.state.context =
                                Some(if key.code == KeyCode::Char('-') {
                                    radius.saturating_sub(1)
                                } else {
                                    radius.saturating_add(1).min(
                                        data.map_or(0, |data| {
                                            data.messages.len()
                                        }),
                                    )
                                });
                            dirty = true;
                            jump = true;
                        }
                        KeyCode::Char('t') => {
                            self.state.expanded = !self.state.expanded;
                            dirty = true;
                        }
                        KeyCode::Char(' ') if !self.rows.is_empty() => {
                            if !self.state.marked.remove(&self.state.selected) {
                                self.state.marked.insert(self.state.selected);
                            }
                            self.status = t(
                                "READER_MARKED",
                                self.zh,
                                &[(
                                    "count",
                                    self.state.marked.len().to_string(),
                                )],
                            );
                        }
                        KeyCode::Char('e')
                            if !self.state.marked.is_empty()
                                && self.state.context.is_none() =>
                        {
                            return Ok(Action::ExportMarked(
                                self.state.marked.iter().copied().collect(),
                            ));
                        }
                        KeyCode::Char('e') if data.is_some() => {
                            match self.state.export(data.unwrap(), self.zh) {
                                Ok(action) => return Ok(action),
                                Err(error) => {
                                    self.status =
                                        render::safe_line(&error.to_string());
                                }
                            }
                        }
                        KeyCode::Char('y') if !self.rows.is_empty() => {
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
                            self.state.refresh_hit();
                            dirty = self.state.context.is_some();
                            jump = true;
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
                                KeyCode::End => {
                                    self.rows.len().saturating_sub(1)
                                }
                                _ => (self.state.selected + 1)
                                    .min(self.rows.len().saturating_sub(1)),
                            };
                            if selected != self.state.selected {
                                let marked =
                                    std::mem::take(&mut self.state.marked);
                                self.state =
                                    State::with_query(&self.query, selected);
                                self.state.marked = marked;
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
    fn export(&self, data: &SessionData, zh: bool) -> crate::Result<Action> {
        let locator = if self.context.is_some() {
            let target = self
                .hits
                .get(self.hit)
                .ok_or_else(|| t("READER_NEED_HIT", zh, &[]))?;
            Some(format!("{}:{}", context::revision(data)?, target + 1))
        } else {
            None
        };
        Ok(Action::Export {
            locator,
            context: self.context.unwrap_or(0),
        })
    }

    fn with_query(query: &Query, selected: usize) -> Self {
        Self {
            selected,
            query: query.clone(),
            expanded: query.keyword.is_some(),
            ..Self::default()
        }
    }

    fn context_range(&self, total: usize) -> Option<std::ops::Range<usize>> {
        let radius = self.context?;
        let &target = self.hits.get(self.hit)?;
        Some(
            target.saturating_sub(radius)
                ..target.saturating_add(radius).saturating_add(1).min(total),
        )
    }

    fn hit_offset(&self, message: usize) -> usize {
        let start = self.starts.get(message).copied().unwrap_or(0);
        let end = self
            .starts
            .get(message + 1)
            .copied()
            .unwrap_or(self.lines.len());
        let query = TextQuery::new(
            self.query.keyword.as_deref().unwrap_or(""),
            Mode::Terms,
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

    fn refresh_hit(&mut self) {
        self.active_hit_line =
            self.hits.get(self.hit).map(|&hit| self.hit_offset(hit));
    }

    fn search(&mut self, data: Option<&SessionData>) -> crate::Result<()> {
        self.hits = data
            .map(|data| context::locate(data, &self.query))
            .transpose()?
            .unwrap_or_default()
            .into_iter()
            .map(|location| location.position - 1)
            .collect();
        self.hit = 0;
        self.active_hit_line = None;
        Ok(())
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
            let range = self.context_range(data.messages.len());
            for (i, message) in data.messages.iter().enumerate() {
                self.starts.push(self.lines.len());
                if range.as_ref().is_some_and(|range| !range.contains(&i)) {
                    continue;
                }
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
            self.lines.push(t(
                if data.is_none() {
                    "READER_NO_MATCHES"
                } else {
                    "READER_EMPTY_BODY"
                },
                zh,
                &[],
            ));
        }
        self.refresh_hit();
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
    scope: &str,
    query: &Query,
    zh: bool,
) {
    let area = frame.area();
    if area.height < 7 || area.width < 20 {
        frame.render_widget(Paragraph::new(t("READER_SMALL", zh, &[])), area);
        return;
    }
    if let Some(offset) = state.help {
        frame.render_widget(
            Paragraph::new(format!(
                "{}\n\n{}\n\n{}",
                render::safe_body(scope),
                t("READER_HELP_FULL", zh, &[]),
                render::safe_body(status)
            ))
            .wrap(Wrap { trim: false })
            .scroll((offset, 0))
            .block(panel(t("READER_HELP_TITLE", zh, &[]), true)),
            area,
        );
        return;
    }
    let areas = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(if area.height >= 12 { 2 } else { 0 }),
        Constraint::Length(u16::from(area.height >= 10)),
        Constraint::Min(1),
        Constraint::Length(1),
        Constraint::Length(2),
    ])
    .split(area);
    frame.render_widget(
        Paragraph::new(rows.get(state.selected).map_or_else(
            || t("READER_SESSIONS", zh, &[]),
            |row| render::safe_line(&row.group),
        ))
        .style(Style::default().add_modifier(Modifier::BOLD)),
        areas[0],
    );
    frame.render_widget(
        Paragraph::new(render::safe_body(scope))
            .wrap(Wrap { trim: false })
            .style(Style::default().fg(Color::DarkGray)),
        areas[1],
    );
    frame.render_widget(
        Paragraph::new(t(
            "READER_SEARCH_STATE",
            zh,
            &[
                (
                    "query",
                    render::safe_line(query.keyword.as_deref().unwrap_or("")),
                ),
                ("count", rows.len().to_string()),
                (
                    "mode",
                    t(
                        if query.mode == Mode::Terms {
                            "READER_TERMS"
                        } else {
                            "READER_PHRASE"
                        },
                        zh,
                        &[],
                    ),
                ),
            ],
        )),
        areas[2],
    );
    if area.width >= 90 {
        let panes = Layout::horizontal([
            Constraint::Length(area.width / 3),
            Constraint::Min(1),
        ])
        .split(areas[3]);
        draw_list(frame, panes[0], rows, state, zh);
        draw_body(frame, panes[1], state, zh);
    } else if state.body_focus {
        draw_body(frame, areas[3], state, zh);
    } else {
        draw_list(frame, areas[3], rows, state, zh);
    }
    let status = state.editing.as_ref().map_or_else(
        || render::safe_line(status),
        |(scope, input)| {
            format!(
                "{} > {}",
                t(
                    match scope {
                        InputScope::Sessions => "READER_INPUT_SESSIONS",
                        InputScope::Messages => "READER_INPUT_MESSAGES",
                    },
                    zh,
                    &[]
                ),
                render::safe_line(input)
            )
        },
    );
    frame.render_widget(
        Paragraph::new(status).style(Style::default().fg(Color::Yellow)),
        areas[4],
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
        areas[5],
    );
}

fn draw_list(
    frame: &mut Frame<'_>,
    area: Rect,
    rows: &[Row],
    state: &State,
    zh: bool,
) {
    if rows.is_empty() {
        frame.render_widget(
            Paragraph::new(t("READER_NO_MATCHES", zh, &[]))
                .wrap(Wrap { trim: false })
                .block(panel(t("READER_SESSIONS", zh, &[]), !state.body_focus)),
            area,
        );
        return;
    }
    let items = rows
        .iter()
        .enumerate()
        .map(|(position, row)| {
            let mut lines = vec![Line::raw(if state.marked.is_empty() {
                row.title.clone()
            } else {
                format!(
                    "{} {}",
                    if state.marked.contains(&position) {
                        "[x]"
                    } else {
                        "[ ]"
                    },
                    row.title
                )
            })];
            for (index, detail) in row.detail.lines().enumerate() {
                let style = if index == 0 {
                    Style::default().fg(Color::DarkGray)
                } else {
                    Style::default()
                };
                lines.extend(
                    wrap(
                        detail,
                        usize::from(area.width.saturating_sub(4).max(1)),
                    )
                    .into_iter()
                    .take(if index == 0 { 1 } else { 2 })
                    .map(|line| Line::styled(line, style)),
                );
            }
            ListItem::new(lines)
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
    let active = state.active_hit_line;
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
    let title = state.context_range(state.starts.len()).map_or_else(
        || {
            format!(
                "{} · {}/{}",
                t("READER_BODY", zh, &[]),
                state.offset + 1,
                state.lines.len()
            )
        },
        |range| {
            t(
                "READER_EXCERPT_RANGE",
                zh,
                &[
                    ("start", (range.start + 1).to_string()),
                    ("end", range.end.to_string()),
                    ("total", state.starts.len().to_string()),
                ],
            )
        },
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
    fn scoped_hits_preview_and_export_share_message_positions() {
        let session = Session::new(
            "fixture".into(),
            "Search evidence".into(),
            std::path::PathBuf::new(),
            Timestamp::UNIX_EPOCH,
            Timestamp::UNIX_EPOCH,
        );
        let data = session.payload(
            [
                ("user", "outside"),
                ("assistant", "database lock ignored"),
                ("user", "database lock first"),
                ("assistant", "context"),
                ("user", "lock database second"),
            ]
            .into_iter()
            .enumerate()
            .map(|(i, (role, text))| {
                Message::new(
                    i.to_string(),
                    role,
                    0,
                    vec![Part::text(text.into(), 0)],
                )
            })
            .collect(),
            Stats::default(),
        );
        let query = Query {
            keyword: Some("database lock".into()),
            mode: Mode::Terms,
            roles: Some(["user".into()].into()),
            ..Query::default()
        };
        let mut state = State::with_query(&query, 0);
        state.search(Some(&data)).unwrap();
        assert_eq!(state.hits, [2, 4]);
        state.context = Some(0);
        state.reflow(Some(&data), None, 60, false);
        assert_eq!(state.context_range(5), Some(2..3));
        assert!(state.lines.join("\n").contains("database lock first"));
        assert!(!state.lines.join("\n").contains("ignored"));
        let Action::Export { locator, context } =
            state.export(&data, false).unwrap()
        else {
            panic!("expected excerpt export");
        };
        assert_eq!(context, 0);
        assert_eq!(
            locator,
            Some(format!("{}:3", context::revision(&data).unwrap()))
        );
        state.context = Some(1);
        state.hit = 1;
        state.reflow(Some(&data), None, 60, false);
        assert_eq!(state.context_range(5), Some(3..5));
        assert!(state.lines.join("\n").contains("context"));
        assert!(!state.lines.join("\n").contains("first"));
        let mut empty = State::default();
        empty.reflow(None, None, 60, false);
        for (width, height) in [(120, 24), (40, 16)] {
            let mut terminal =
                Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal
                .draw(|frame| {
                    draw(
                        frame,
                        &[],
                        &empty,
                        "No matching sessions",
                        "Provider: codex\nRole: user",
                        &query,
                        false,
                    );
                })
                .unwrap();
            let screen = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(ratatui::buffer::Cell::symbol)
                .collect::<String>();
            assert!(screen.contains("Provider: codex"));
            assert!(screen.contains("Role: user"));
            assert!(screen.contains("No matching sessions"));
            println!("\nEmpty {width}x{height}");
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
    }

    #[test]
    #[ignore = "Manual release benchmark; run scripts/benchmark_reader_redraw.py"]
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
                query: Query {
                    keyword: Some("needle".into()),
                    ..Query::default()
                },
                ..State::default()
            };
            state.search(Some(&data)).unwrap();
            assert_eq!(state.hits, vec![0]);
            state.reflow(Some(&data), None, 65, false);
            state.offset = state.hit_offset(0);
            let mut terminal =
                Terminal::new(TestBackend::new(100, 24)).unwrap();
            for _ in 0..5 {
                terminal
                    .draw(|frame| {
                        draw(
                            frame,
                            &rows,
                            &state,
                            "benchmark",
                            "",
                            &Query::default(),
                            false,
                        );
                    })
                    .unwrap();
            }
            let iterations = 200;
            let start = Instant::now();
            for _ in 0..iterations {
                terminal
                    .draw(|frame| {
                        draw(
                            frame,
                            &rows,
                            &state,
                            "benchmark",
                            "",
                            &Query::default(),
                            false,
                        );
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
        state.query.keyword = Some("hidden-needle".into());
        state.search(Some(&data)).unwrap();
        assert_eq!(state.hits, vec![1]);
        state.reflow(Some(&data), None, 60, true);
        assert_eq!(state.active_hit_line, Some(state.starts[1]));
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
            let expected =
                state.lines.iter().position(|line| line.contains("hidden"));
            assert!(expected.is_some());
            assert_eq!(state.active_hit_line, expected);
            let mut terminal =
                Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal
                .draw(|frame| {
                    draw(
                        frame,
                        &rows,
                        &state,
                        "测试状态",
                        "",
                        &Query::default(),
                        true,
                    );
                })
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
        state.expanded = false;
        state.reflow(Some(&data), None, 18, true);
        assert_eq!(state.active_hit_line, Some(state.starts[1]));
        state.query.keyword = None;
        state.search(Some(&data)).unwrap();
        assert_eq!(state.active_hit_line, None);
        state.reflow(Some(&data), None, 18, true);
        assert_eq!(state.active_hit_line, None);
    }
}
