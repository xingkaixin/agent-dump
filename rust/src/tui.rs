use crossterm::{
    event::{
        self, DisableBracketedPaste, EnableBracketedPaste, Event, KeyCode, KeyEventKind,
        KeyModifiers,
    },
    execute,
};
use ratatui::{
    Frame,
    layout::{Constraint, Layout},
    style::{Color, Modifier, Style},
    text::{Line, Text},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph},
};
use std::io::{self, IsTerminal};

pub fn available() -> bool {
    io::stdin().is_terminal() && io::stdout().is_terminal()
}

struct Restore;
impl Drop for Restore {
    fn drop(&mut self) {
        let _ = execute!(io::stdout(), DisableBracketedPaste);
        ratatui::restore();
    }
}

pub struct Row {
    pub title: String,
    pub detail: String,
    pub group: String,
}

fn help(zh: bool, multiple: bool) -> &'static str {
    match (zh, multiple) {
        (true, true) => "↑↓ 移动 · 空格选择 · a 全选 · i 反选 · Enter 确认 · q/Esc 取消",
        (false, true) => "↑↓ move · Space select · a all · i invert · Enter confirm · q/Esc cancel",
        (true, false) => "↑↓ 移动 · Enter 确认 · q/Esc 取消",
        (false, false) => "↑↓ move · Enter confirm · q/Esc cancel",
    }
}

#[derive(PartialEq)]
enum ChoiceMode {
    Single,
    Multiple,
    Confirm,
}

pub fn select(
    title: &str,
    rows: &[Row],
    multiple: bool,
    initial: usize,
    zh: bool,
) -> crate::Result<Option<Vec<usize>>> {
    select_mode(
        title,
        rows,
        if multiple {
            ChoiceMode::Multiple
        } else {
            ChoiceMode::Single
        },
        initial,
        zh,
    )
}

fn select_mode(
    title: &str,
    rows: &[Row],
    mode: ChoiceMode,
    initial: usize,
    zh: bool,
) -> crate::Result<Option<Vec<usize>>> {
    let multiple = mode == ChoiceMode::Multiple;
    if rows.is_empty() {
        return Ok(Some(Vec::new()));
    }
    let _restore = Restore;
    let mut terminal = ratatui::try_init()?;
    execute!(io::stdout(), EnableBracketedPaste)?;
    let mut cursor = initial.min(rows.len() - 1);
    let mut selected = vec![false; rows.len()];
    let mut state = ListState::default().with_selected(Some(cursor));
    loop {
        terminal.draw(|frame| {
            draw_selection(frame, title, rows, multiple, &selected, &mut state, zh)
        })?;
        let Event::Key(key) = event::read()? else {
            continue;
        };
        if key.kind == KeyEventKind::Release {
            continue;
        }
        if key.code == KeyCode::Esc
            || matches!(key.code, KeyCode::Char('q' | 'Q'))
            || (key.code == KeyCode::Char('c') && key.modifiers.contains(KeyModifiers::CONTROL))
        {
            return Ok(None);
        }
        match key.code {
            KeyCode::Char('y' | 'Y') if mode == ChoiceMode::Confirm => return Ok(Some(vec![0])),
            KeyCode::Char('n' | 'N') if mode == ChoiceMode::Confirm => return Ok(Some(vec![1])),
            KeyCode::Up | KeyCode::Char('k') => {
                cursor = cursor.checked_sub(1).unwrap_or(rows.len() - 1)
            }
            KeyCode::Down | KeyCode::Char('j') => cursor = (cursor + 1) % rows.len(),
            KeyCode::Home => cursor = 0,
            KeyCode::End => cursor = rows.len() - 1,
            KeyCode::PageUp => {
                cursor =
                    cursor.saturating_sub(terminal.size()?.height.saturating_sub(4).max(1) as usize)
            }
            KeyCode::PageDown => {
                cursor = (cursor + terminal.size()?.height.saturating_sub(4).max(1) as usize)
                    .min(rows.len() - 1)
            }
            KeyCode::Char(' ') if multiple => selected[cursor] = !selected[cursor],
            KeyCode::Char('a') if multiple => {
                let select = !selected.iter().all(|v| *v);
                selected.fill(select);
            }
            KeyCode::Char('i') if multiple => selected.iter_mut().for_each(|v| *v = !*v),
            KeyCode::Enter => {
                return Ok(Some(if multiple {
                    selected
                        .iter()
                        .enumerate()
                        .filter_map(|(i, s)| s.then_some(i))
                        .collect()
                } else {
                    vec![cursor]
                }));
            }
            _ => {}
        }
        state.select(Some(cursor));
    }
}

fn draw_selection(
    frame: &mut Frame<'_>,
    title: &str,
    rows: &[Row],
    multiple: bool,
    selected: &[bool],
    state: &mut ListState,
    zh: bool,
) {
    let areas = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(1),
        Constraint::Length(2),
    ])
    .split(frame.area());
    frame.render_widget(
        Paragraph::new(title).style(Style::default().add_modifier(Modifier::BOLD)),
        areas[0],
    );
    let items = rows
        .iter()
        .enumerate()
        .map(|(index, row)| {
            let prefix = if !multiple {
                ""
            } else if selected[index] {
                "[x] "
            } else {
                "[ ] "
            };
            let mut lines = Vec::new();
            if !row.group.is_empty() {
                lines.push(Line::styled(
                    row.group.clone(),
                    Style::default().fg(Color::Cyan),
                ));
            }
            lines.push(Line::raw(format!("{prefix}{}", row.title)));
            if !row.detail.is_empty() {
                lines.push(Line::styled(
                    format!("    {}", row.detail),
                    Style::default().fg(Color::DarkGray),
                ));
            }
            ListItem::new(Text::from(lines))
        })
        .collect::<Vec<_>>();
    frame.render_stateful_widget(
        List::new(items)
            .highlight_symbol("› ")
            .highlight_style(Style::default().add_modifier(Modifier::REVERSED)),
        areas[1],
        state,
    );
    frame.render_widget(
        Paragraph::new(help(zh, multiple)).block(Block::default().borders(Borders::TOP)),
        areas[2],
    );
}

pub fn input(prompt: &str, default: &str, secret: bool, zh: bool) -> crate::Result<Option<String>> {
    use unicode_width::UnicodeWidthChar;
    let _restore = Restore;
    let mut terminal = ratatui::try_init()?;
    execute!(io::stdout(), EnableBracketedPaste)?;
    let mut text: Vec<char> = default.chars().collect();
    let mut cursor = text.len();
    loop {
        terminal.draw(|frame| {
            let areas = Layout::vertical([
                Constraint::Length(2),
                Constraint::Length(3),
                Constraint::Min(0),
            ])
            .split(frame.area());
            frame.render_widget(
                Paragraph::new(prompt).style(Style::default().add_modifier(Modifier::BOLD)),
                areas[0],
            );
            let width = areas[1].width.saturating_sub(2) as usize;
            let visible: Vec<char> = if secret {
                vec!['*'; text.len()]
            } else {
                text.clone()
            };
            let mut start = cursor;
            let mut offset = 0;
            while start > 0 {
                let next = visible[start - 1].width().unwrap_or(0);
                if offset + next >= width {
                    break;
                }
                start -= 1;
                offset += next;
            }
            frame.render_widget(
                Paragraph::new(visible[start..].iter().collect::<String>())
                    .block(Block::bordered()),
                areas[1],
            );
            if width > 0 && areas[1].height > 1 {
                frame.set_cursor_position((areas[1].x + 1 + offset as u16, areas[1].y + 1));
            }
            frame.render_widget(
                Paragraph::new(if zh {
                    "Enter 确认 · Esc/Ctrl+C 取消"
                } else {
                    "Enter confirm · Esc/Ctrl+C cancel"
                }),
                areas[2],
            );
        })?;
        match event::read()? {
            Event::Paste(value) => {
                let value = crate::render::safe_line(&value);
                let added: Vec<_> = value.chars().collect();
                let count = added.len();
                text.splice(cursor..cursor, added);
                cursor += count;
            }
            Event::Key(key) if key.kind != KeyEventKind::Release => {
                if key.code == KeyCode::Esc
                    || (key.code == KeyCode::Char('c')
                        && key.modifiers.contains(KeyModifiers::CONTROL))
                {
                    return Ok(None);
                }
                match key.code {
                    KeyCode::Enter => return Ok(Some(text.iter().collect())),
                    KeyCode::Left => cursor = cursor.saturating_sub(1),
                    KeyCode::Right => cursor = (cursor + 1).min(text.len()),
                    KeyCode::Home => cursor = 0,
                    KeyCode::End => cursor = text.len(),
                    KeyCode::Backspace if cursor > 0 => {
                        cursor -= 1;
                        text.remove(cursor);
                    }
                    KeyCode::Delete if cursor < text.len() => {
                        text.remove(cursor);
                    }
                    KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                        text.drain(..cursor);
                        cursor = 0;
                    }
                    KeyCode::Char(c)
                        if !key
                            .modifiers
                            .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT)
                            && !c.is_control() =>
                    {
                        text.insert(cursor, c);
                        cursor += 1;
                    }
                    _ => {}
                }
            }
            _ => {}
        }
    }
}

pub fn confirm(prompt: &str, default: bool, zh: bool) -> crate::Result<bool> {
    let rows = [
        Row {
            title: if zh { "是" } else { "Yes" }.into(),
            detail: String::new(),
            group: String::new(),
        },
        Row {
            title: if zh { "否" } else { "No" }.into(),
            detail: String::new(),
            group: String::new(),
        },
    ];
    Ok(select_mode(
        prompt,
        &rows,
        ChoiceMode::Confirm,
        usize::from(!default),
        zh,
    )?
    .is_some_and(|v| v == [0]))
}

pub fn secret_line(prompt: &str) -> crate::Result<Option<String>> {
    use std::io::Write;
    struct RestoreInput;
    impl Drop for RestoreInput {
        fn drop(&mut self) {
            let _ = execute!(io::stderr(), DisableBracketedPaste);
            let _ = crossterm::terminal::disable_raw_mode();
        }
    }
    let mut output = io::stderr();
    write!(output, "{prompt}")?;
    output.flush()?;
    let guard = RestoreInput;
    crossterm::terminal::enable_raw_mode()?;
    execute!(output, EnableBracketedPaste)?;
    let mut text = String::new();
    let result = loop {
        match event::read()? {
            Event::Paste(value) => text.push_str(&crate::render::safe_line(&value)),
            Event::Key(key) if key.kind != KeyEventKind::Release => match key.code {
                KeyCode::Enter => break Some(text),
                KeyCode::Esc => break None,
                KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => break None,
                KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => text.clear(),
                KeyCode::Backspace => {
                    text.pop();
                }
                KeyCode::Char(c)
                    if !key
                        .modifiers
                        .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT)
                        && !c.is_control() =>
                {
                    text.push(c)
                }
                _ => {}
            },
            _ => {}
        }
    };
    drop(guard);
    writeln!(output)?;
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn selection_draws_unicode_at_small_and_resized_dimensions() {
        let rows = [Row {
            title: "修复认证 😺".into(),
            detail: "cwd=项目/目录 | msgs=2".into(),
            group: "[今天] (1 个会话)".into(),
        }];
        for (width, height) in [(1, 1), (12, 4), (24, 8), (80, 24)] {
            let mut terminal =
                ratatui::Terminal::new(ratatui::backend::TestBackend::new(width, height)).unwrap();
            let mut state = ListState::default().with_selected(Some(0));
            terminal
                .draw(|frame| {
                    draw_selection(frame, "选择会话", &rows, true, &[true], &mut state, true)
                })
                .unwrap();
            assert_eq!(terminal.backend().buffer().area.width, width);
            if width == 80 {
                let text = terminal
                    .backend()
                    .buffer()
                    .content
                    .iter()
                    .map(|c| c.symbol())
                    .collect::<String>();
                assert!(text.replace(' ', "").contains("修复认证"));
                assert!(text.contains("[x]"));
                assert!(text.replace(' ', "").contains("今天"));
            }
        }
    }
}
