use super::tui;
use agent_dump_core::{
    output::{i18n::t, render},
    query::{
        Query, context,
        text::{Mode, TextQuery},
        transcript::message_texts,
    },
    session::{Message, Part, SessionData},
};
use crossterm::{
    clipboard::CopyToClipboard,
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
    execute,
};
use ratatui::{
    Frame,
    layout::{Constraint, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Wrap},
};
use std::collections::BTreeSet;
use std::time::Duration;
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

const ACCENT: Color = Color::Cyan;
const HIT: Color = Color::Yellow;
const DIM: Color = Color::DarkGray;
// Long enough to swallow key repeat while scrolling the list, short enough
// that a single keypress still feels immediate.
const SETTLE: Duration = Duration::from_millis(120);

pub struct Entry {
    pub title: String,
    pub provider: String,
    pub day: String,
    pub time: String,
    pub count: String,
    pub place: String,
    pub snippet: String,
    pub meta: String,
    pub uri: String,
}

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
enum Overlay {
    #[default]
    None,
    Help(u16),
    Editing(InputScope, String),
}

struct Slot {
    header: bool,
    top: usize,
    start: usize,
    end: usize,
}

#[derive(Clone, Copy)]
struct Chunk {
    first: usize,
    last: usize,
    folded: bool,
    detailed: bool,
}

impl Chunk {
    const fn contains(self, message: usize) -> bool {
        self.first <= message && message <= self.last
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    User,
    Role,
    Text,
    Tool,
    Blank,
}

#[derive(Clone)]
struct Row {
    gutter: String,
    kind: Kind,
    text: String,
}

impl Row {
    const fn new(gutter: String, kind: Kind, text: String) -> Self {
        Self { gutter, kind, text }
    }
    const fn text(text: String) -> Self {
        Self::new(String::new(), Kind::Text, text)
    }
}

struct ViewRow {
    marker: &'static str,
    row: Row,
    active: bool,
}

#[derive(Default)]
struct View {
    rows: Vec<ViewRow>,
    first: usize,
    last: usize,
}

#[derive(Default)]
struct Body {
    chunks: Vec<Chunk>,
    rows: Vec<Option<Vec<Row>>>,
    notice: String,
    width: usize,
    top: (usize, usize),
    active: Option<(usize, usize)>,
    total: usize,
    built: bool,
    zh: bool,
}

#[derive(Default)]
struct State {
    selected: usize,
    body_focus: bool,
    expanded: bool,
    query: Query,
    finder: Option<TextQuery>,
    overlay: Overlay,
    context: Option<usize>,
    hits: Vec<usize>,
    hit: usize,
    marked: BTreeSet<usize>,
    body: Body,
}

pub struct Reader {
    terminal: ratatui::DefaultTerminal,
    _restore: tui::Restore,
    entries: Vec<Entry>,
    slots: Vec<Slot>,
    list_offset: usize,
    query: Query,
    finder: Option<TextQuery>,
    scope: String,
    state: State,
    pending: Option<Event>,
    page: usize,
    zh: bool,
    pub status: String,
    pub partial: bool,
}

impl Reader {
    pub fn new(
        entries: Vec<Entry>,
        query: &Query,
        scope: String,
        zh: bool,
    ) -> crate::Result<Self> {
        let restore = tui::Restore;
        Ok(Self {
            terminal: tui::init()?,
            _restore: restore,
            slots: slots(&entries),
            entries,
            list_offset: 0,
            state: State::with_query(query, 0),
            finder: finder(query),
            query: query.clone(),
            scope,
            pending: None,
            page: 1,
            zh,
            status: String::new(),
            partial: false,
        })
    }

    pub fn set_results(&mut self, entries: Vec<Entry>, query: &Query) {
        self.slots = slots(&entries);
        self.entries = entries;
        self.list_offset = 0;
        self.finder = finder(query);
        self.query = query.clone();
        self.state = State::with_query(query, 0);
    }

    pub const fn selected(&self) -> usize {
        self.state.selected
    }

    fn geometry(&self) -> crate::Result<Geometry> {
        let size = self.terminal.size()?;
        Ok(Geometry::new(
            Rect::new(0, 0, size.width, size.height),
            self.state.body_focus,
        ))
    }

    fn measure(&mut self) -> crate::Result<()> {
        if let Some(body) = self.geometry()?.body {
            let content = split_body(body).1;
            self.page = usize::from(content.height).max(1);
            self.state.body.set_width(
                usize::from(content.width)
                    .saturating_sub(gutter_width(self.state.body.total) + 2)
                    .max(1),
            );
        }
        Ok(())
    }

    fn render(&mut self, data: Option<&SessionData>) -> crate::Result<()> {
        let geometry = self.geometry()?;
        if let (Some(list), Some(slot)) =
            (geometry.list, self.slots.get(self.state.selected))
        {
            self.list_offset = follow(
                self.list_offset,
                slot.top,
                slot.end,
                usize::from(list.height),
            );
        }
        let view = if geometry.body.is_some() && self.state.body.built {
            self.measure()?;
            self.state.body.view(
                data,
                self.page,
                &self.state.hits,
                self.state.hit,
            )
        } else {
            View::default()
        };
        let Self {
            terminal,
            entries,
            slots,
            list_offset,
            query,
            finder,
            scope,
            state,
            status,
            partial,
            zh,
            ..
        } = self;
        let screen = Screen {
            entries,
            slots,
            list_offset: *list_offset,
            query,
            finder: finder.as_ref(),
            scope,
            state,
            status,
            partial: *partial,
            view: &view,
            zh: *zh,
        };
        terminal.draw(|frame| draw(frame, &geometry, &screen))?;
        Ok(())
    }

    fn reload(
        &mut self,
        data: Option<&SessionData>,
        error: Option<&str>,
        jump: bool,
    ) -> crate::Result<()> {
        self.state.rebuild(data, error, self.zh);
        self.measure()?;
        if jump {
            self.state.jump(data);
        }
        Ok(())
    }

    fn toggle_excerpt(&mut self) {
        if self.state.context.is_some() {
            self.state.context = None;
            self.status.clear();
        } else if !self.state.hits.is_empty() {
            self.state.context = Some(3);
            self.state.body_focus = true;
            self.status.clear();
        } else {
            self.status = t("READER_NEED_HIT", self.zh, &[]);
        }
    }

    fn submit(
        &mut self,
        scope: InputScope,
        input: String,
        data: Option<&SessionData>,
    ) -> crate::Result<Option<Action>> {
        if matches!(scope, InputScope::Sessions) {
            self.status = t("READER_SEARCHING", self.zh, &[]);
            self.render(data)?;
            return Ok(Some(Action::Search(input)));
        }
        self.state.query = Query {
            keyword: Some(input),
            ..Query::default()
        };
        self.state.context = None;
        self.state.search(data);
        self.state.body_focus = true;
        self.status = t(
            "READER_MATCHES",
            self.zh,
            &[("count", self.state.hits.len().to_string())],
        );
        Ok(None)
    }

    fn preview(&mut self, selected: usize) {
        let marked = std::mem::take(&mut self.state.marked);
        self.state = State::with_query(&self.query, selected);
        self.state.marked = marked;
        self.status.clear();
    }

    fn navigate(
        &mut self,
        key: KeyCode,
        data: Option<&SessionData>,
    ) -> crate::Result<bool> {
        let count = self.entries.len();
        let mut selected = step(self.state.selected, key, count);
        if selected == self.state.selected {
            return Ok(false);
        }
        loop {
            if selected != self.state.selected {
                self.preview(selected);
            }
            self.render(data)?;
            if !event::poll(SETTLE)? {
                return Ok(true);
            }
            match event::read()? {
                Event::Key(key) if key.kind == KeyEventKind::Release => {}
                Event::Key(key) if moves(key.code) => {
                    selected = step(selected, key.code, count);
                }
                event => {
                    self.pending = Some(event);
                    return Ok(true);
                }
            }
        }
    }

    pub fn next(
        &mut self,
        data: Option<&SessionData>,
        error: Option<&str>,
    ) -> crate::Result<Action> {
        let previous_hit = self.state.hit;
        self.state.search(data);
        self.state.hit =
            previous_hit.min(self.state.hits.len().saturating_sub(1));
        let fresh = !self.state.body.built;
        self.reload(data, error, fresh && !self.state.hits.is_empty())?;
        loop {
            self.render(data)?;
            let size = self.terminal.size()?;
            match self.pending.take().map_or_else(event::read, Ok)? {
                Event::Paste(text) => {
                    if let Overlay::Editing(_, input) = &mut self.state.overlay
                    {
                        input.push_str(&render::safe_body(&text));
                    }
                }
                Event::Key(key) if key.kind != KeyEventKind::Release => {
                    if key.code == KeyCode::Char('c')
                        && key.modifiers.contains(KeyModifiers::CONTROL)
                    {
                        return Ok(Action::Quit);
                    }
                    match &mut self.state.overlay {
                        Overlay::Help(offset) => {
                            if scroll_help(offset, key.code, size.height) {
                                self.state.overlay = Overlay::None;
                            }
                            continue;
                        }
                        Overlay::Editing(scope, input) => {
                            match key.code {
                                KeyCode::Esc => {
                                    self.state.overlay = Overlay::None;
                                }
                                KeyCode::Backspace => {
                                    input.pop();
                                }
                                KeyCode::Char(c) if !c.is_control() => {
                                    input.push(c);
                                }
                                KeyCode::Enter => {
                                    let scope = *scope;
                                    let input = std::mem::take(input);
                                    self.state.overlay = Overlay::None;
                                    if let Some(action) =
                                        self.submit(scope, input, data)?
                                    {
                                        return Ok(action);
                                    }
                                    let jump = !self.state.hits.is_empty();
                                    self.reload(data, error, jump)?;
                                }
                                _ => {}
                            }
                            continue;
                        }
                        Overlay::None => {}
                    }
                    if let Some(action) = self.handle(key.code, data, error)? {
                        return Ok(action);
                    }
                }
                _ => {}
            }
        }
    }

    fn handle(
        &mut self,
        key: KeyCode,
        data: Option<&SessionData>,
        error: Option<&str>,
    ) -> crate::Result<Option<Action>> {
        let page = self.page;
        match key {
            KeyCode::Esc if self.state.context.is_some() => {
                self.state.context = None;
                self.status.clear();
                self.reload(data, error, true)?;
            }
            KeyCode::Esc | KeyCode::Char('q' | 'Q') => {
                return Ok(Some(Action::Quit));
            }
            KeyCode::Tab | KeyCode::BackTab => {
                self.state.body_focus = !self.state.body_focus;
            }
            KeyCode::Enter | KeyCode::Right => self.state.body_focus = true,
            KeyCode::Left => self.state.body_focus = false,
            KeyCode::Char('/') => {
                self.state.overlay =
                    Overlay::Editing(InputScope::Messages, String::new());
            }
            KeyCode::Char('s') => {
                self.state.overlay =
                    Overlay::Editing(InputScope::Sessions, String::new());
            }
            KeyCode::Char('c') => {
                return Ok(Some(Action::Search(String::new())));
            }
            KeyCode::Char('?') => self.state.overlay = Overlay::Help(0),
            KeyCode::Char('x') => {
                self.toggle_excerpt();
                self.reload(data, error, true)?;
            }
            KeyCode::Char('+' | '=' | '-') if self.state.context.is_some() => {
                let radius = self.state.context.unwrap_or(0);
                self.state.context = Some(if key == KeyCode::Char('-') {
                    radius.saturating_sub(1)
                } else {
                    radius
                        .saturating_add(1)
                        .min(data.map_or(0, |data| data.messages.len()))
                });
                self.reload(data, error, true)?;
            }
            KeyCode::Char('t') => {
                self.state.expanded = !self.state.expanded;
                self.reload(data, error, false)?;
            }
            KeyCode::Char(' ') if !self.entries.is_empty() => {
                if !self.state.marked.remove(&self.state.selected) {
                    self.state.marked.insert(self.state.selected);
                }
                self.status = t(
                    "READER_MARKED",
                    self.zh,
                    &[("count", self.state.marked.len().to_string())],
                );
            }
            KeyCode::Char('e')
                if !self.state.marked.is_empty()
                    && self.state.context.is_none() =>
            {
                return Ok(Some(Action::ExportMarked(
                    self.state.marked.iter().copied().collect(),
                )));
            }
            KeyCode::Char('e') if data.is_some() => {
                match self.state.export(data.unwrap(), self.zh) {
                    Ok(action) => return Ok(Some(action)),
                    Err(error) => {
                        self.status = render::safe_line(&error.to_string());
                    }
                }
            }
            KeyCode::Char('y') if !self.entries.is_empty() => {
                self.status = match execute!(
                    self.terminal.backend_mut(),
                    CopyToClipboard::to_clipboard_from(
                        &self.entries[self.state.selected].uri
                    )
                ) {
                    Ok(()) => t("READER_COPY_REQUEST", self.zh, &[]),
                    Err(error) => render::safe_line(&error.to_string()),
                };
            }
            KeyCode::Char('n' | 'N') if !self.state.hits.is_empty() => {
                let count = self.state.hits.len();
                self.state.hit = if key == KeyCode::Char('N') {
                    (self.state.hit + count - 1) % count
                } else {
                    (self.state.hit + 1) % count
                };
                self.state.body_focus = true;
                self.reload(data, error, true)?;
            }
            KeyCode::Up | KeyCode::Char('k') if self.state.body_focus => {
                self.state.body.up(data, 1);
            }
            KeyCode::Down | KeyCode::Char('j') if self.state.body_focus => {
                self.state.body.down(data, 1);
            }
            KeyCode::PageUp => {
                self.state.body_focus = true;
                self.state.body.up(data, page);
            }
            KeyCode::PageDown => {
                self.state.body_focus = true;
                self.state.body.down(data, page);
            }
            KeyCode::Home if self.state.body_focus => self.state.body.home(),
            KeyCode::End if self.state.body_focus => {
                self.state.body.end(data, page);
            }
            code if moves(code) => {
                if self.navigate(code, data)? {
                    return Ok(Some(Action::Select));
                }
            }
            _ => {}
        }
        Ok(None)
    }
}

const fn moves(key: KeyCode) -> bool {
    matches!(
        key,
        KeyCode::Up
            | KeyCode::Down
            | KeyCode::Home
            | KeyCode::End
            | KeyCode::Char('k' | 'j')
    )
}

const fn scroll_help(offset: &mut u16, key: KeyCode, height: u16) -> bool {
    match key {
        KeyCode::Esc | KeyCode::Char('?' | 'q') => return true,
        KeyCode::Up | KeyCode::Char('k') => *offset = offset.saturating_sub(1),
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
    false
}

fn step(selected: usize, key: KeyCode, rows: usize) -> usize {
    match key {
        KeyCode::Up | KeyCode::Char('k') => selected.saturating_sub(1),
        KeyCode::Home => 0,
        KeyCode::End => rows.saturating_sub(1),
        _ => (selected + 1).min(rows.saturating_sub(1)),
    }
}

const fn follow(offset: usize, top: usize, end: usize, height: usize) -> usize {
    if top < offset {
        top
    } else if end > offset + height {
        end.saturating_sub(height)
    } else {
        offset
    }
}

fn finder(query: &Query) -> Option<TextQuery> {
    query
        .keyword
        .as_deref()
        .map(|keyword| TextQuery::new(keyword, Mode::Terms))
        .filter(|finder| !finder.literals.is_empty())
}

fn slots(entries: &[Entry]) -> Vec<Slot> {
    let mut line = 0;
    let mut previous: Option<&str> = None;
    entries
        .iter()
        .map(|entry| {
            let header =
                !entry.day.is_empty() && previous != Some(entry.day.as_str());
            previous = Some(entry.day.as_str());
            if header && line > 0 {
                line += 1;
            }
            let top = line;
            line += usize::from(header);
            let start = line;
            line += if entry.snippet.is_empty() { 2 } else { 3 };
            Slot {
                header,
                top,
                start,
                end: line,
            }
        })
        .collect()
}

impl State {
    fn with_query(query: &Query, selected: usize) -> Self {
        Self {
            selected,
            query: query.clone(),
            ..Self::default()
        }
    }

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

    fn context_range(&self, total: usize) -> Option<std::ops::Range<usize>> {
        let radius = self.context?;
        let &target = self.hits.get(self.hit)?;
        Some(
            target.saturating_sub(radius)
                ..target.saturating_add(radius).saturating_add(1).min(total),
        )
    }

    fn search(&mut self, data: Option<&SessionData>) {
        self.hits = data
            .map(|data| context::hits(data, &self.query))
            .unwrap_or_default();
        self.hit = 0;
        self.finder = finder(&self.query);
    }

    fn rebuild(
        &mut self,
        data: Option<&SessionData>,
        error: Option<&str>,
        zh: bool,
    ) {
        let range =
            data.and_then(|data| self.context_range(data.messages.len()));
        let body = &mut self.body;
        let anchor = body
            .chunks
            .get(body.top.0)
            .map(|chunk| (chunk.first, body.top.1));
        body.chunks.clear();
        body.notice.clear();
        body.active = None;
        body.built = true;
        body.zh = zh;
        body.total = data.map_or(0, |data| data.messages.len());
        if let Some(error) = error {
            error.clone_into(&mut body.notice);
        } else if let Some(data) = data {
            for index in range.unwrap_or(0..data.messages.len()) {
                let detailed =
                    self.expanded || self.hits.binary_search(&index).is_ok();
                let folded = !detailed
                    && message_texts(&data.messages[index]).is_empty();
                match body.chunks.last_mut() {
                    Some(last)
                        if folded && last.folded && last.last + 1 == index =>
                    {
                        last.last = index;
                    }
                    _ => body.chunks.push(Chunk {
                        first: index,
                        last: index,
                        folded,
                        detailed,
                    }),
                }
            }
            if body.chunks.is_empty() {
                body.notice = t("READER_EMPTY_BODY", zh, &[]);
            }
        } else {
            body.notice = t("READER_NO_MATCHES", zh, &[]);
        }
        body.rows = vec![None; body.chunks.len()];
        body.top = anchor
            .and_then(|(first, row)| {
                let chunk = body.chunk_of(first)?;
                Some((
                    chunk,
                    if body.chunks[chunk].first == first {
                        row
                    } else {
                        0
                    },
                ))
            })
            .unwrap_or_default();
    }

    fn jump(&mut self, data: Option<&SessionData>) {
        if let (Some(data), Some(&message)) = (data, self.hits.get(self.hit)) {
            self.body.locate(data, message, self.finder.as_ref());
        }
    }
}

impl Body {
    fn set_width(&mut self, width: usize) {
        if width != self.width {
            self.width = width;
            self.rows.iter_mut().for_each(|rows| *rows = None);
        }
    }

    fn chunk_of(&self, message: usize) -> Option<usize> {
        let index = self.chunks.partition_point(|chunk| chunk.last < message);
        self.chunks
            .get(index)
            .is_some_and(|chunk| chunk.contains(message))
            .then_some(index)
    }

    fn rows_of(&mut self, data: &SessionData, chunk: usize) -> &[Row] {
        let (span, width, zh) = (self.chunks[chunk], self.width, self.zh);
        self.rows[chunk]
            .get_or_insert_with(|| chunk_rows(data, span, width, zh))
    }

    fn down(&mut self, data: Option<&SessionData>, lines: usize) {
        let Some(data) = data else { return };
        let (mut chunk, mut row) = self.top;
        for _ in 0..lines {
            if chunk >= self.chunks.len() {
                break;
            }
            if row + 1 < self.rows_of(data, chunk).len() {
                row += 1;
            } else if chunk + 1 < self.chunks.len() {
                chunk += 1;
                row = 0;
            } else {
                break;
            }
        }
        self.top = (chunk, row);
    }

    fn up(&mut self, data: Option<&SessionData>, lines: usize) {
        let Some(data) = data else { return };
        let (mut chunk, mut row) = self.top;
        for _ in 0..lines {
            if row > 0 {
                row -= 1;
            } else if chunk > 0 {
                chunk -= 1;
                row = self.rows_of(data, chunk).len().saturating_sub(1);
            } else {
                break;
            }
        }
        self.top = (chunk, row);
    }

    const fn home(&mut self) {
        self.top = (0, 0);
    }

    fn end(&mut self, data: Option<&SessionData>, page: usize) {
        let Some(found) = data else { return };
        let Some(last) = self.chunks.len().checked_sub(1) else {
            return;
        };
        let row = self.rows_of(found, last).len().saturating_sub(1);
        self.top = (last, row);
        self.up(data, page.saturating_sub(1));
    }

    fn locate(
        &mut self,
        data: &SessionData,
        message: usize,
        finder: Option<&TextQuery>,
    ) {
        let Some(chunk) = self.chunk_of(message) else {
            return;
        };
        let row = finder
            .and_then(|finder| {
                self.rows_of(data, chunk).iter().position(|row| {
                    row.kind == Kind::Text
                        && finder.first_literal_span(&row.text).is_some()
                })
            })
            .unwrap_or(0);
        self.top = (chunk, row);
        self.active = Some((chunk, row));
        self.up(Some(data), 2);
    }

    fn view(
        &mut self,
        data: Option<&SessionData>,
        height: usize,
        hits: &[usize],
        hit: usize,
    ) -> View {
        let mut view = View::default();
        let Some(data) = data.filter(|_| self.notice.is_empty()) else {
            view.rows = wrap(&render::safe_body(&self.notice), self.width)
                .into_iter()
                .take(height)
                .map(|text| ViewRow {
                    marker: "",
                    row: Row::text(text),
                    active: false,
                })
                .collect();
            return view;
        };
        let (mut chunk, mut row) = self.top;
        if let Some(rows) =
            (chunk < self.chunks.len()).then(|| self.rows_of(data, chunk).len())
        {
            row = row.min(rows.saturating_sub(1));
            self.top = (chunk, row);
        }
        view.first = self.chunks.get(chunk).map_or(0, |chunk| chunk.first);
        let active = self.active;
        let target = hits.get(hit).copied();
        while view.rows.len() < height && chunk < self.chunks.len() {
            let span = self.chunks[chunk];
            let marker = if target.is_some_and(|m| span.contains(m)) {
                "▶"
            } else if hits
                .get(hits.partition_point(|&m| m < span.first))
                .is_some_and(|&m| m <= span.last)
            {
                "◆"
            } else {
                ""
            };
            for (index, item) in
                self.rows_of(data, chunk).iter().enumerate().skip(row)
            {
                if view.rows.len() == height {
                    break;
                }
                view.rows.push(ViewRow {
                    marker: if index == 0 { marker } else { "" },
                    row: item.clone(),
                    active: active == Some((chunk, index)),
                });
            }
            view.last = span.last;
            chunk += 1;
            row = 0;
        }
        view
    }
}

fn chunk_rows(
    data: &SessionData,
    chunk: Chunk,
    width: usize,
    zh: bool,
) -> Vec<Row> {
    let gutter = format!("#{}", chunk.first + 1);
    let messages = &data.messages[chunk.first..=chunk.last];
    let mut rows = Vec::new();
    if chunk.folded {
        let summary = tools(messages);
        rows.push(Row::new(
            gutter,
            Kind::Tool,
            if summary.is_empty() {
                t("READER_NO_TEXT", zh, &[])
            } else {
                summary
            },
        ));
    } else {
        let message = &messages[0];
        let (kind, label) = match message.role.as_str() {
            "user" => (Kind::User, t("READER_ROLE_USER", zh, &[])),
            "assistant" => (Kind::Role, t("READER_ROLE_ASSISTANT", zh, &[])),
            role => (Kind::Role, render::safe_line(role)),
        };
        rows.push(Row::new(gutter, kind, label));
        let text = message_texts(message).join("\n\n");
        if !text.is_empty() {
            rows.extend(
                wrap(&render::safe_body(&text), width)
                    .into_iter()
                    .map(Row::text),
            );
        }
        if chunk.detailed {
            for part in &message.parts {
                if let Part::Tool(tool) = part {
                    rows.push(Row::new(
                        String::new(),
                        Kind::Tool,
                        format!("▸ {}", render::safe_line(&tool.tool)),
                    ));
                    let state = serde_json::to_string_pretty(&tool.state)
                        .unwrap_or_default();
                    rows.extend(
                        wrap(&render::safe_body(&state), width)
                            .into_iter()
                            .map(Row::text),
                    );
                }
            }
        } else {
            let summary = tools(messages);
            if !summary.is_empty() {
                rows.push(Row::new(String::new(), Kind::Tool, summary));
            }
        }
    }
    rows.push(Row::new(String::new(), Kind::Blank, String::new()));
    rows
}

fn tools(messages: &[Message]) -> String {
    let mut counts: Vec<(&str, usize)> = Vec::new();
    for part in messages.iter().flat_map(|message| &message.parts) {
        if let Part::Tool(tool) = part {
            match counts.iter_mut().find(|(name, _)| *name == tool.tool) {
                Some((_, count)) => *count += 1,
                None => counts.push((&tool.tool, 1)),
            }
        }
    }
    if counts.is_empty() {
        return String::new();
    }
    let names = counts
        .iter()
        .map(|&(name, count)| {
            let name = render::safe_line(name);
            if count > 1 {
                format!("{name} ×{count}")
            } else {
                name
            }
        })
        .collect::<Vec<_>>()
        .join(" · ");
    format!("▸ {names}")
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

fn fit(text: &str, max: usize) -> String {
    if text.width() <= max {
        return text.to_owned();
    }
    let mut out = String::new();
    let mut used = 0;
    for c in text.chars() {
        let size = c.width().unwrap_or(0);
        if used + size + 1 > max {
            break;
        }
        out.push(c);
        used += size;
    }
    if max > 0 {
        out.push('…');
    }
    out
}

fn pad(text: &str, size: usize) -> String {
    let mut out = fit(text, size);
    let used = out.width();
    out.extend(std::iter::repeat_n(' ', size.saturating_sub(used)));
    out
}

fn marks(text: &str, finder: &TextQuery) -> Vec<std::ops::Range<usize>> {
    let mut ranges = Vec::new();
    let mut at = 0;
    while let Some(span) = finder.first_literal_span(&text[at..]) {
        if span.is_empty() {
            break;
        }
        ranges.push(at + span.start..at + span.end);
        at += span.end;
    }
    ranges
}

fn highlight(
    text: &str,
    finder: Option<&TextQuery>,
    base: Style,
    mark: Style,
) -> Vec<Span<'static>> {
    let mut spans = Vec::new();
    let mut at = 0;
    for range in finder.map(|finder| marks(text, finder)).unwrap_or_default() {
        if range.start > at {
            spans.push(Span::styled(text[at..range.start].to_owned(), base));
        }
        spans.push(Span::styled(text[range.clone()].to_owned(), mark));
        at = range.end;
    }
    if at < text.len() {
        spans.push(Span::styled(text[at..].to_owned(), base));
    }
    spans
}

const fn gutter_width(total: usize) -> usize {
    let mut digits = 1;
    let mut rest = total / 10;
    while rest > 0 {
        digits += 1;
        rest /= 10;
    }
    digits + 4
}

struct Geometry {
    top: Rect,
    upper_rule: Rect,
    lower_rule: Rect,
    status: Rect,
    list: Option<Rect>,
    divider: Option<Rect>,
    body: Option<Rect>,
}

impl Geometry {
    fn new(area: Rect, body_focus: bool) -> Self {
        let inner = Rect {
            x: area.x.saturating_add(1),
            width: area.width.saturating_sub(2),
            ..area
        };
        let rows = Layout::vertical([
            Constraint::Length(1),
            Constraint::Length(1),
            Constraint::Min(1),
            Constraint::Length(1),
            Constraint::Length(1),
        ])
        .split(inner);
        let main = rows[2];
        let (list, divider, body) = if area.width >= 90 {
            let width = u16::try_from(u32::from(main.width) * 35 / 100)
                .unwrap_or(u16::MAX)
                .clamp(32, 64);
            (
                Some(Rect { width, ..main }),
                Some(Rect {
                    x: main.x + width + 1,
                    width: 1,
                    ..main
                }),
                Some(Rect {
                    x: main.x + width + 3,
                    width: main.width.saturating_sub(width + 3),
                    ..main
                }),
            )
        } else if body_focus {
            (None, None, Some(main))
        } else {
            (Some(main), None, None)
        };
        Self {
            top: rows[0],
            upper_rule: rows[1],
            lower_rule: rows[3],
            status: rows[4],
            list,
            divider,
            body,
        }
    }
}

const fn split_body(area: Rect) -> (Option<Rect>, Rect) {
    if area.height < 8 {
        return (None, area);
    }
    (
        Some(Rect { height: 3, ..area }),
        Rect {
            y: area.y + 3,
            height: area.height - 3,
            ..area
        },
    )
}

struct Screen<'a> {
    entries: &'a [Entry],
    slots: &'a [Slot],
    list_offset: usize,
    query: &'a Query,
    finder: Option<&'a TextQuery>,
    scope: &'a str,
    state: &'a State,
    status: &'a str,
    partial: bool,
    view: &'a View,
    zh: bool,
}

fn dim() -> Style {
    Style::default().fg(DIM)
}

fn bold() -> Style {
    Style::default().add_modifier(Modifier::BOLD)
}

fn spread(
    mut left: Vec<Span<'static>>,
    right: Vec<Span<'static>>,
    width: usize,
) -> Line<'static> {
    let used: usize = left.iter().chain(&right).map(Span::width).sum();
    left.push(Span::raw(" ".repeat(width.saturating_sub(used))));
    left.extend(right);
    Line::from(left)
}

fn draw(frame: &mut Frame<'_>, geometry: &Geometry, screen: &Screen<'_>) {
    let area = frame.area();
    let zh = screen.zh;
    if area.height < 7 || area.width < 20 {
        frame.render_widget(Paragraph::new(t("READER_SMALL", zh, &[])), area);
        return;
    }
    if let Overlay::Help(offset) = screen.state.overlay {
        let mut scope = render::safe_body(screen.scope);
        if screen.partial {
            scope = format!("{scope}\n{}", t("READER_PARTIAL", zh, &[]));
        }
        frame.render_widget(
            Paragraph::new(format!(
                "{}\n\n{}\n\n{}",
                scope,
                t("READER_HELP_FULL", zh, &[]),
                render::safe_body(screen.status)
            ))
            .wrap(Wrap { trim: false })
            .scroll((offset, 0))
            .block(
                Block::default()
                    .borders(Borders::ALL)
                    .title(t("READER_HELP_TITLE", zh, &[]))
                    .border_style(Style::default().fg(ACCENT)),
            ),
            area,
        );
        return;
    }
    draw_top(frame, geometry.top, area.width >= 90, screen);
    for rule in [geometry.upper_rule, geometry.lower_rule] {
        frame.render_widget(
            Paragraph::new("─".repeat(usize::from(rule.width))).style(dim()),
            rule,
        );
    }
    if let Some(list) = geometry.list {
        draw_list(frame, list, screen);
    }
    if let Some(divider) = geometry.divider {
        frame.render_widget(
            Paragraph::new(vec![Line::raw("│"); usize::from(divider.height)])
                .style(dim()),
            divider,
        );
    }
    if let Some(body) = geometry.body {
        draw_body(frame, body, screen);
    }
    draw_status(frame, geometry.status, screen);
}

fn draw_top(frame: &mut Frame<'_>, area: Rect, wide: bool, screen: &Screen) {
    let zh = screen.zh;
    let width = usize::from(area.width);
    let count = t(
        "READER_COUNT_SESSIONS",
        zh,
        &[("count", screen.entries.len().to_string())],
    );
    let mut right = match screen
        .query
        .keyword
        .as_deref()
        .filter(|keyword| !keyword.trim().is_empty())
    {
        Some(keyword) => vec![
            Span::styled(
                format!("{} ", t("READER_SEARCH_LABEL", zh, &[])),
                dim(),
            ),
            Span::styled(
                fit(&render::safe_line(keyword), width / 3),
                bold().fg(HIT),
            ),
            Span::styled(
                format!(
                    " · {} · {count}",
                    t(
                        if screen.query.mode == Mode::Terms {
                            "READER_TERMS"
                        } else {
                            "READER_PHRASE"
                        },
                        zh,
                        &[]
                    )
                ),
                dim(),
            ),
        ],
        None => vec![Span::styled(count, dim())],
    };
    if screen.partial {
        right.insert(
            0,
            Span::styled(
                format!("{} · ", t("READER_PARTIAL_TAG", zh, &[])),
                Style::default().fg(HIT),
            ),
        );
    }
    let mut left = vec![Span::styled("agent-dump", bold().fg(ACCENT))];
    let room = width.saturating_sub(
        right.iter().map(Span::width).sum::<usize>() + left[0].width() + 6,
    );
    if wide && room > 8 {
        left.push(Span::raw("   "));
        left.push(Span::styled(fit(screen.scope, room), dim()));
    }
    frame.render_widget(Paragraph::new(spread(left, right, width)), area);
}

fn draw_list(frame: &mut Frame<'_>, area: Rect, screen: &Screen) {
    if screen.entries.is_empty() {
        frame.render_widget(
            Paragraph::new(t("READER_NO_MATCHES", screen.zh, &[]))
                .wrap(Wrap { trim: false }),
            area,
        );
        return;
    }
    let width = usize::from(area.width);
    let height = usize::from(area.height);
    let offset = screen.list_offset;
    let provider = screen
        .entries
        .iter()
        .map(|entry| entry.provider.width())
        .max()
        .unwrap_or(0)
        .min(16);
    let mut lines: Vec<Line> = Vec::with_capacity(height);
    for (index, (entry, slot)) in
        screen.entries.iter().zip(screen.slots).enumerate()
    {
        if slot.end <= offset {
            continue;
        }
        if slot.top >= offset + height {
            break;
        }
        let mut item = Vec::new();
        if slot.header {
            item.push((
                slot.top,
                Line::styled(format!("  {}", entry.day), dim()),
            ));
        }
        item.extend(
            entry_lines(entry, index, (width, provider), screen)
                .into_iter()
                .enumerate()
                .map(|(line, content)| (slot.start + line, content)),
        );
        for (line, content) in item {
            if line < offset || line >= offset + height {
                continue;
            }
            lines.resize(line - offset, Line::default());
            lines.push(content);
        }
    }
    frame.render_widget(Paragraph::new(lines), area);
}

fn entry_lines(
    entry: &Entry,
    index: usize,
    (width, provider): (usize, usize),
    screen: &Screen,
) -> Vec<Line<'static>> {
    let state = screen.state;
    let selected = index == state.selected;
    let bar = if selected {
        Span::styled(
            "▎ ",
            Style::default().fg(if state.body_focus { DIM } else { ACCENT }),
        )
    } else {
        Span::raw("  ")
    };
    let inner = width.saturating_sub(4);
    let title = pad(&entry.title, inner);
    let mark = if state.marked.contains(&index) {
        " ●"
    } else {
        ""
    };
    let meta = format!(
        "{} {} {:>7}  {}",
        pad(&entry.provider, provider + 1),
        entry.time,
        entry.count,
        entry.place
    );
    let mut lines = vec![
        Line::from(vec![
            bar.clone(),
            Span::styled(
                title,
                if selected { bold() } else { Style::default() },
            ),
            Span::styled(mark, Style::default().fg(ACCENT)),
        ]),
        Line::from(vec![
            bar.clone(),
            Span::styled(fit(&meta, width.saturating_sub(2)), dim()),
        ]),
    ];
    if !entry.snippet.is_empty() {
        let mut spans = vec![bar];
        spans.extend(highlight(
            &fit(&entry.snippet, width.saturating_sub(2)),
            screen.finder,
            Style::default(),
            bold().fg(HIT),
        ));
        lines.push(Line::from(spans));
    }
    lines
}

fn position(screen: &Screen) -> String {
    let state = screen.state;
    let body = &state.body;
    if body.total == 0 || screen.view.rows.is_empty() || !body.notice.is_empty()
    {
        return String::new();
    }
    let mut parts = Vec::new();
    if !state.hits.is_empty() {
        parts.push(t(
            "READER_HIT_POSITION",
            screen.zh,
            &[
                ("hit", (state.hit + 1).to_string()),
                ("count", state.hits.len().to_string()),
            ],
        ));
    }
    parts.push(state.context_range(body.total).map_or_else(
        || {
            let view = screen.view;
            if view.first == view.last {
                format!("#{} / {}", view.first + 1, body.total)
            } else {
                format!(
                    "#{}–{} / {}",
                    view.first + 1,
                    view.last + 1,
                    body.total
                )
            }
        },
        |range| {
            t(
                "READER_EXCERPT_RANGE",
                screen.zh,
                &[
                    ("start", (range.start + 1).to_string()),
                    ("end", range.end.to_string()),
                    ("total", body.total.to_string()),
                ],
            )
        },
    ));
    parts.join(" · ")
}

fn draw_body(frame: &mut Frame<'_>, area: Rect, screen: &Screen) {
    let state = screen.state;
    let (header, content) = split_body(area);
    let entry = screen.entries.get(state.selected);
    if let (Some(header), Some(entry)) = (header, entry) {
        let width = usize::from(header.width);
        let position = position(screen);
        let title_style = if state.body_focus {
            bold().fg(ACCENT)
        } else {
            bold()
        };
        let title =
            fit(&entry.title, width.saturating_sub(position.width() + 2));
        frame.render_widget(
            Paragraph::new(vec![
                spread(
                    vec![Span::styled(title, title_style)],
                    vec![Span::styled(position, dim())],
                    width,
                ),
                Line::styled(fit(&entry.meta, width), dim()),
                Line::styled("─".repeat(width), dim()),
            ]),
            header,
        );
    }
    if !state.body.built {
        let text = t(
            "READER_LOADING",
            screen.zh,
            &[("count", entry.map_or_else(String::new, |e| e.count.clone()))],
        );
        frame.render_widget(
            Paragraph::new(Line::styled(text, dim()).centered()),
            Rect {
                y: content.y + content.height / 2,
                height: 1,
                ..content
            },
        );
        return;
    }
    let gutter = gutter_width(state.body.total);
    let lines = screen
        .view
        .rows
        .iter()
        .map(|row| body_line(row, gutter, state.finder.as_ref()))
        .collect::<Vec<_>>();
    frame.render_widget(
        Paragraph::new(lines),
        Rect {
            width: content.width.saturating_sub(2),
            ..content
        },
    );
    if state.body.notice.is_empty() && state.body.total > 0 {
        draw_scrollbar(
            frame,
            Rect {
                x: content.right().saturating_sub(1),
                width: 1,
                ..content
            },
            screen.view,
            state.body.total,
        );
    }
}

fn body_line(
    row: &ViewRow,
    gutter: usize,
    finder: Option<&TextQuery>,
) -> Line<'static> {
    let mut spans = vec![
        Span::styled(pad(row.marker, 2), Style::default().fg(HIT)),
        Span::styled(pad(&row.row.gutter, gutter - 2), dim()),
    ];
    let text = row.row.text.clone();
    match row.row.kind {
        Kind::User => spans.push(Span::styled(text, bold().fg(ACCENT))),
        Kind::Role | Kind::Tool => spans.push(Span::styled(text, dim())),
        Kind::Text => spans.extend(highlight(
            &text,
            finder,
            Style::default(),
            if row.active {
                bold().fg(Color::Black).bg(HIT)
            } else {
                bold().fg(HIT)
            },
        )),
        Kind::Blank => {}
    }
    Line::from(spans)
}

fn draw_scrollbar(
    frame: &mut Frame<'_>,
    area: Rect,
    view: &View,
    total: usize,
) {
    let height = usize::from(area.height);
    if view.rows.is_empty() || height == 0 {
        return;
    }
    let start = view.first * height / total;
    let length = ((view.last - view.first + 1) * height / total).max(1);
    let lines = (0..height)
        .map(|y| {
            if (start..start + length).contains(&y) {
                Line::styled("┃", Style::default().fg(ACCENT))
            } else {
                Line::styled("│", dim())
            }
        })
        .collect::<Vec<_>>();
    frame.render_widget(Paragraph::new(lines), area);
}

fn badge(label: &str) -> Span<'static> {
    Span::styled(format!(" {label} "), bold().fg(Color::Black).bg(ACCENT))
}

fn draw_status(frame: &mut Frame<'_>, area: Rect, screen: &Screen) {
    let zh = screen.zh;
    let state = screen.state;
    let width = usize::from(area.width);
    if let Overlay::Editing(scope, input) = &state.overlay {
        let label = t(
            match scope {
                InputScope::Sessions => "READER_INPUT_SESSIONS",
                InputScope::Messages => "READER_INPUT_MESSAGES",
            },
            zh,
            &[],
        );
        let label = badge(&label);
        let room = width.saturating_sub(label.width() + 4);
        frame.render_widget(
            Paragraph::new(Line::from(vec![
                label,
                Span::styled(" › ", Style::default().fg(ACCENT)),
                Span::raw(fit(&render::safe_line(input), room)),
                Span::styled("▏", Style::default().fg(ACCENT)),
            ])),
            area,
        );
        return;
    }
    let mode = if state.context.is_some() {
        "READER_MODE_EXCERPT"
    } else if screen.finder.is_some() || !state.hits.is_empty() {
        "READER_MODE_SEARCH"
    } else {
        "READER_MODE_BROWSE"
    };
    let label = badge(&t(mode, zh, &[]));
    let right = if screen.status.is_empty() {
        let mut parts = Vec::new();
        if !state.marked.is_empty() {
            parts.push(t(
                "READER_SELECTED",
                zh,
                &[("count", state.marked.len().to_string())],
            ));
        }
        if !screen.entries.is_empty() {
            parts.push(format!(
                "{} / {}",
                state.selected + 1,
                screen.entries.len()
            ));
        }
        Span::styled(parts.join(" · "), dim())
    } else {
        Span::styled(
            fit(
                &render::safe_line(screen.status),
                width.saturating_sub(label.width() + 2),
            ),
            Style::default().fg(HIT),
        )
    };
    let hints = t(
        if state.context.is_some() {
            "READER_HINTS_EXCERPT"
        } else if !state.hits.is_empty() {
            "READER_HINTS_HITS"
        } else if state.body_focus {
            "READER_HINTS_BODY"
        } else {
            "READER_HINTS_LIST"
        },
        zh,
        &[],
    );
    let mut room = width.saturating_sub(label.width() + right.width() + 2);
    let mut left = vec![label];
    for hint in hints.split(" · ") {
        let (key, text) = hint.split_once(' ').unwrap_or((hint, ""));
        let size = 3 + key.width() + text.width();
        if size > room {
            break;
        }
        room -= size;
        left.push(Span::raw("  "));
        left.push(Span::styled(key.to_owned(), bold()));
        left.push(Span::styled(format!(" {text}"), dim()));
    }
    frame.render_widget(Paragraph::new(spread(left, vec![right], width)), area);
}

#[cfg(test)]
mod tests {
    use super::*;
    use agent_dump_core::session::{Session, Stats, timestamp::Timestamp};
    use ratatui::{Terminal, backend::TestBackend};

    fn session(messages: Vec<Message>) -> SessionData {
        Session::new(
            "test".into(),
            "Reader test".into(),
            std::path::PathBuf::new(),
            Timestamp::UNIX_EPOCH,
            Timestamp::UNIX_EPOCH,
        )
        .payload(messages, Stats::default())
    }

    fn text(role: &str, body: &str) -> Message {
        Message::new("m".into(), role, 0, vec![Part::text(body.into(), 0)])
    }

    fn tool(name: &str) -> Message {
        Message::new(
            "m".into(),
            "assistant",
            0,
            vec![Part::tool(name, "call", serde_json::json!({}), 0)],
        )
    }

    #[test]
    fn list_keeps_offset_when_moving_back_up() {
        let mut offset = 0;
        for end in [2, 4, 6, 8, 10, 12] {
            offset = follow(offset, end - 2, end, 6);
        }
        assert_eq!(offset, 6);
        assert_eq!(follow(offset, 8, 10, 6), 6);
        assert_eq!(follow(offset, 6, 8, 6), 6);
        assert_eq!(follow(offset, 4, 6, 6), 4);
    }

    #[test]
    fn tool_only_messages_fold_unless_they_hit() {
        let data = session(vec![
            text("user", "start"),
            tool("Bash"),
            tool("Bash"),
            tool("Read"),
            text("assistant", "done"),
        ]);
        let mut state = State::default();
        state.rebuild(Some(&data), None, false);
        let spans: Vec<_> = state
            .body
            .chunks
            .iter()
            .map(|chunk| (chunk.first, chunk.last, chunk.folded))
            .collect();
        assert_eq!(spans, [(0, 0, false), (1, 3, true), (4, 4, false)]);
        state.body.set_width(40);
        assert_eq!(state.body.rows_of(&data, 1)[0].text, "▸ Bash ×2 · Read");

        state.hits = vec![2];
        state.rebuild(Some(&data), None, false);
        let spans: Vec<_> = state
            .body
            .chunks
            .iter()
            .map(|chunk| (chunk.first, chunk.last))
            .collect();
        assert_eq!(spans, [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]);
    }

    #[test]
    fn partial_results_stay_marked_after_status_clears() {
        let mut state = State::default();
        state.rebuild(None, None, false);
        let area = Rect::new(0, 0, 100, 24);
        let geometry = Geometry::new(area, false);
        let screen = Screen {
            entries: &[],
            slots: &[],
            list_offset: 0,
            query: &Query::default(),
            finder: None,
            scope: "",
            state: &state,
            status: "",
            partial: true,
            view: &View::default(),
            zh: false,
        };
        let mut terminal = Terminal::new(TestBackend::new(100, 24)).unwrap();
        terminal
            .draw(|frame| draw(frame, &geometry, &screen))
            .unwrap();
        let top = terminal.backend().buffer().content[..100]
            .iter()
            .map(ratatui::buffer::Cell::symbol)
            .collect::<String>();
        assert!(top.contains("partial results · 0 sessions"), "{top}");
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
            let data = session(vec![text(
                "assistant",
                &format!("{}\nneedle", "x".repeat(chars)),
            )]);
            let entries = (0..row_count)
                .map(|i| Entry {
                    title: format!("Reader benchmark session {i}"),
                    provider: "Codex".into(),
                    day: "10-02".into(),
                    time: "12:00".into(),
                    count: "1".into(),
                    place: "benchmark".into(),
                    snippet: String::new(),
                    meta: "Codex · benchmark".into(),
                    uri: format!("codex://benchmark-{i}"),
                })
                .collect::<Vec<_>>();
            let slots = slots(&entries);
            let mut state = State {
                body_focus: true,
                query: Query {
                    keyword: Some("needle".into()),
                    ..Query::default()
                },
                ..State::default()
            };
            state.search(Some(&data));
            assert_eq!(state.hits, vec![0]);
            state.rebuild(Some(&data), None, false);
            let area = Rect::new(0, 0, 100, 24);
            let geometry = Geometry::new(area, true);
            let content = split_body(geometry.body.unwrap()).1;
            state.body.set_width(
                usize::from(content.width) - gutter_width(state.body.total) - 2,
            );
            state.jump(Some(&data));
            let query = Query::default();
            let mut terminal =
                Terminal::new(TestBackend::new(100, 24)).unwrap();
            let mut redraw = |terminal: &mut Terminal<TestBackend>| {
                let view = state.body.view(
                    Some(&data),
                    usize::from(content.height),
                    &state.hits,
                    state.hit,
                );
                let screen = Screen {
                    entries: &entries,
                    slots: &slots,
                    list_offset: 0,
                    query: &query,
                    finder: None,
                    scope: "",
                    state: &state,
                    status: "benchmark",
                    partial: false,
                    view: &view,
                    zh: false,
                };
                terminal
                    .draw(|frame| draw(frame, &geometry, &screen))
                    .unwrap();
            };
            for _ in 0..5 {
                redraw(&mut terminal);
            }
            let iterations = 200;
            let start = Instant::now();
            for _ in 0..iterations {
                redraw(&mut terminal);
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
}
