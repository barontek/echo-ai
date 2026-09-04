//! TUI app shell: crossterm setup, event loop (keyboard + worker
//! events), and the ratatui render pass.
//!
//! Depends on: `ratatui`, `crossterm`, `tokio`, crate models,
//! `echo-ai-core`.

use std::sync::Arc;
use std::time::Duration;

use crossterm::event::{self, Event, KeyCode, KeyEvent, KeyModifiers};
use crossterm::execute;
use crossterm::terminal::{
    EnterAlternateScreen, LeaveAlternateScreen, disable_raw_mode, enable_raw_mode,
};
use echo_ai_core::agent::message::Message;
use echo_ai_core::agent::run::{Agent, AgentConfig, AgentEvent};
use echo_ai_core::config::Config;
use echo_ai_core::llm::http::{HttpClient, ReqwestClient};
use echo_ai_core::llm::provider::LlmMessage;
use echo_ai_core::safety::SafetyConfig;
use echo_ai_core::session::SessionManager;
use echo_ai_core::tools::registry::Registry;
use echo_ai_core::tools::search::SearchProvider;
use echo_ai_core::tools::semantic::SemanticIndex;
use ratatui::Terminal;
use ratatui::backend::CrosstermBackend;
use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use tokio::sync::mpsc;

use crate::chat::ChatBuffer;
use crate::dialogs::{Dialog, DialogResult, DialogState};
use crate::input::LineEditor;
use crate::keys::{self, Keymap};

/// Message types the UI thread processes.
#[derive(Debug)]
enum UiEvent {
    Key(KeyEvent),
    Agent(AgentEvent),
    Tick,
}

/// Builds the shared agent for the TUI (config + wiring, no session
/// manager unless persistence is on).
///
/// # Errors
/// `Error::Config` when the provider cannot be built.
pub fn build_agent(config: &Config) -> Result<Arc<Agent>, echo_ai_core::error::Error> {
    let safety = Arc::new(SafetyConfig::from_config(&config.safety, None));
    let http: Arc<dyn HttpClient> = Arc::new(ReqwestClient::new());
    let index = Arc::new(SemanticIndex::new());
    let search = SearchProvider::from_config(config).map(Arc::new);
    let registry = Arc::new(Registry::build(
        config,
        search,
        index,
        Arc::new(echo_ai_core::browser::BrowserManager::new()),
    ));
    let provider = echo_ai_core::llm::factory::create_provider(config, Some(http.clone()), None)?;
    Ok(Arc::new(Agent {
        provider,
        registry,
        config: AgentConfig::from(config),
        safety,
        app_config: config.clone(),
        session: Arc::new(std::sync::Mutex::new(None)),
        tracker: None,
        ask_user: None,
        http,
    }))
}

/// Runs the TUI until quit.
///
/// # Errors
/// Terminal setup/teardown failures.
pub async fn run_tui(config: Config, agent: Arc<Agent>) -> std::io::Result<()> {
    enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let result = run_loop(&mut terminal, config, agent).await;
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    result
}

/// The main loop: dispatch events, update state, render.
///
/// The length is inherent: one loop body per event source (keyboard,
/// agent, dialogs) — the original implementation's `tui.c` poll loop was the same
/// shape.
#[allow(clippy::too_many_lines)] // event loop: one arm per source
async fn run_loop(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
    config: Config,
    agent: Arc<Agent>,
) -> std::io::Result<()> {
    let (agent_tx, agent_rx) = mpsc::channel::<AgentEvent>(128);
    let (_, mut ui_rx) = mpsc::channel::<UiEvent>(128);

    // Keymap with defaults (mirroring the C TUI's bindings).
    let mut keymap = Keymap::new();
    keymap.bind("ctrl+space", "leader");
    keymap.bind("ctrl+space", "open_palette");
    keymap.bind("ctrl+n", "new_chat");
    keymap.bind("ctrl+c", "quit");
    keymap.bind("ctrl+l", "clear");

    let mut chat = ChatBuffer::new();
    let mut input = LineEditor::new();
    let mut dialog: Option<DialogState> = None;
    let mut status = String::from("ready");
    let mut running = false;
    let mut cancel = None::<tokio_util::sync::CancellationToken>;
    let mut title = String::from("Echo AI");
    let mut session_id = String::new();
    let mut agent_rx = agent_rx;

    // Optional session store (persistence).
    let mut session_mgr: Option<Arc<SessionManager>> = None;
    if config.session.enabled {
        let home = std::env::var("HOME").unwrap_or_else(|_| String::from("."));
        let dir = std::path::PathBuf::from(home).join(".config/echo-ai");
        // A wrong/missing password is reported, not fatal — chat still
        // works, persistence is just off.
        match SessionManager::open(&dir, &std::env::var("ECHO_AI_PASSWORD").unwrap_or_default()) {
            Ok(sm) => session_mgr = Some(Arc::new(sm)),
            Err(e) => status = format!("session store unavailable: {e}"),
        }
    }

    loop {
        // Render.
        terminal.draw(|f| {
            render_frame(f, &chat, &input, dialog.as_ref(), &status, &title, running);
        })?;

        // Wait for the next event: keyboard (crossterm's blocking read runs
        // on a worker thread), agent (streaming), or a 200ms tick for
        // cursor blink.
        let ui_event = tokio::select! {
            e = ui_rx.recv() => e,
            e = agent_rx.recv() => e.map(UiEvent::Agent),
            e = tokio::task::spawn_blocking(event::read) => match e {
                Ok(Ok(Event::Key(k))) => Some(UiEvent::Key(k)),
                _ => Some(UiEvent::Tick),
            },
            () = tokio::time::sleep(Duration::from_millis(200)) => Some(UiEvent::Tick),
        };

        match ui_event {
            Some(UiEvent::Agent(event)) => {
                handle_agent_event(
                    &mut chat,
                    &mut status,
                    &mut running,
                    &mut cancel,
                    &mut title,
                    event,
                );
            }
            Some(UiEvent::Key(key)) => {
                if let Some(d) = &mut dialog {
                    if let Some(result) = d.handle_key(&to_model_key(&key)) {
                        let kind = d.kind.clone();
                        dialog = None;
                        match result {
                            DialogResult::Text(text) => match &kind {
                                Dialog::Ask {
                                    is_approval: true, ..
                                } => {
                                    status = if text.eq_ignore_ascii_case("yes") {
                                        String::from("approved")
                                    } else {
                                        String::from("denied")
                                    };
                                }
                                Dialog::Ask { .. } => {
                                    status = format!("answered: {text}");
                                }
                                Dialog::Password { .. } => {
                                    status = String::from("password accepted");
                                }
                                _ => {}
                            },
                            DialogResult::Confirmed => {
                                if matches!(kind, Dialog::ConfirmQuit) {
                                    return Ok(());
                                }
                                status = String::from("selected");
                            }
                            DialogResult::Cancelled => {
                                status = String::from("cancelled");
                            }
                        }
                    }
                    continue;
                }
                if let Some(action) = keymap.feed(&to_model_key(&key)) {
                    match action.as_str() {
                        "quit" => return Ok(()),
                        "clear" => chat = ChatBuffer::new(),
                        "open_palette" => {
                            dialog = Some(DialogState::open(Dialog::Pick(String::from("model"))));
                        }
                        "new_chat" => {
                            chat = ChatBuffer::new();
                            session_id = String::new();
                        }
                        _ => {}
                    }
                    continue;
                }
                match key.code {
                    KeyCode::Enter => {
                        let text = std::mem::take(&mut input.buffer);
                        if !text.is_empty() && !running {
                            input.commit();
                            chat.push(crate::chat::Block {
                                role: String::from("user"),
                                text: text.clone(),
                            });
                            start_turn(
                                &mut running,
                                &mut cancel,
                                &agent,
                                &chat,
                                &mut session_mgr,
                                session_id.as_str(),
                                &title,
                                &agent_tx,
                            );
                            status = String::from("running...");
                        }
                    }
                    KeyCode::Backspace => input.backspace(),
                    KeyCode::Delete => input.delete(),
                    KeyCode::Left => input.move_cursor(-1),
                    KeyCode::Right => input.move_cursor(1),
                    KeyCode::Home => input.home(),
                    KeyCode::End => input.end(),
                    KeyCode::Up => input.recall(-1),
                    KeyCode::Down => input.recall(1),
                    KeyCode::Esc => keymap.cancel_chord(),
                    KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                        if running {
                            if let Some(c) = &cancel {
                                c.cancel();
                            }
                        } else {
                            return Ok(());
                        }
                    }
                    KeyCode::Char(c) => input.insert(&c.to_string()),
                    _ => {}
                }
            }
            _ => {}
        }
    }
}

/// Converts a crossterm key to the model key.
fn to_model_key(key: &KeyEvent) -> keys::Key {
    match key.code {
        KeyCode::Char(c) if key.modifiers.contains(KeyModifiers::CONTROL) => {
            keys::Key::Char(((c.to_ascii_lowercase() as u8) - b'a' + 1) as char)
        }
        KeyCode::Char(c) => keys::Key::Char(c),
        KeyCode::Enter => keys::Key::Named(String::from("enter")),
        KeyCode::Esc => keys::Key::Named(String::from("esc")),
        KeyCode::Backspace => keys::Key::Char('\u{7f}'),
        _ => keys::Key::Named(format!("{:?}", key.code).to_ascii_lowercase()),
    }
}

/// Starts a turn on the agent (spawns the run task).
///
/// The argument count is wiring, not logic: every subsystem the turn
/// touches is threaded through (same shape as the original implementation's
/// `tui_worker.c`).
#[allow(clippy::too_many_arguments)] // subsystem wiring
fn start_turn(
    running: &mut bool,
    cancel: &mut Option<tokio_util::sync::CancellationToken>,
    agent: &Arc<Agent>,
    chat: &ChatBuffer,
    session_mgr: &mut Option<Arc<SessionManager>>,
    session_id: &str,
    title: &str,
    agent_tx: &mpsc::Sender<AgentEvent>,
) {
    *running = true;
    let token = tokio_util::sync::CancellationToken::new();
    *cancel = Some(token.clone());

    let messages: Vec<LlmMessage> = chat
        .blocks
        .iter()
        .map(|b| LlmMessage {
            role: b.role.clone(),
            content: b.text.clone(),
            tool_calls: Vec::new(),
            tool_call_id: None,
        })
        .collect();
    let agent = Arc::clone(agent);
    let tx = agent_tx.clone();
    let sm = session_mgr.clone();
    let sid = session_id.to_string();
    let title_out = title.to_string();
    tokio::spawn(async move {
        let result = agent.run(messages, tx.clone(), token).await;
        let _ = tx.send(AgentEvent::Done).await;
        // Persist + title.
        if let Ok(res) = &result
            && let Some(sm) = sm
            && let Some(mut session) = sm.load_session(&sid).ok().flatten()
        {
            session.messages = res
                .messages
                .iter()
                .map(|m| Message {
                    id: None,
                    parent_id: None,
                    fork_group_id: None,
                    role: m.role.clone(),
                    content: m.content.clone(),
                    thinking: None,
                    phase: None,
                    provider_state: None,
                    tool_calls: m.tool_calls.clone(),
                    tool_call_id: m.tool_call_id.clone(),
                    tool_name: None,
                    error_category: None,
                    timestamp: echo_ai_core::agent::message::now_epoch_secs(),
                })
                .collect();
            let _ = sm.save_session(&session);
        }
        let _ = title_out;
    });
}

/// Handles one agent event in the UI.
fn handle_agent_event(
    chat: &mut ChatBuffer,
    status: &mut String,
    running: &mut bool,
    cancel: &mut Option<tokio_util::sync::CancellationToken>,
    title: &mut String,
    event: AgentEvent,
) {
    match event {
        AgentEvent::Chunk { content, thinking } => {
            chat.append_to_last("assistant", &content);
            if let Some(t) = thinking.as_deref() {
                chat.append_to_last("thinking", t);
            }
        }
        AgentEvent::ToolStart { name, .. } => {
            chat.push(crate::chat::Block {
                role: String::from("tool"),
                text: format!("▶ {name}"),
            });
        }
        AgentEvent::ToolEnd { name, ok, summary } => {
            let marker = if ok { "✓" } else { "✗" };
            chat.push(crate::chat::Block {
                role: String::from("tool"),
                text: format!("{marker} {name}: {summary}"),
            });
        }
        AgentEvent::Error { message } => {
            chat.push(crate::chat::Block {
                role: String::from("error"),
                text: message,
            });
            *status = String::from("error");
        }
        AgentEvent::Done => {
            *running = false;
            *cancel = None;
            *status = String::from("ready");
            // Auto-title the first turn.
            if title == "Echo AI"
                && let Some(first_user) = chat.blocks.iter().find(|b| b.role == "user")
            {
                let title_text = first_user
                    .text
                    .split_whitespace()
                    .take(6)
                    .collect::<Vec<_>>()
                    .join(" ");
                *title = title_text;
            }
        }
    }
}

/// Renders the frame: chat pane, input pane, status bar, dialog.
fn render_frame(
    f: &mut ratatui::Frame<'_>,
    chat: &ChatBuffer,
    input: &LineEditor,
    dialog: Option<&DialogState>,
    status: &str,
    title: &str,
    running: bool,
) {
    let chunks = Layout::vertical([
        Constraint::Min(3),
        Constraint::Length(3),
        Constraint::Length(1),
    ])
    .split(f.area());

    let (lines, offset) = chat.layout(chunks[0].width as usize, chunks[0].height as usize);
    let visible: Vec<Line> = lines
        .iter()
        .skip(offset)
        .map(|l| Line::from(Span::raw(l.clone())))
        .collect();
    let chat_block = Block::default().borders(Borders::ALL).title(Span::styled(
        title,
        Style::default().add_modifier(Modifier::BOLD),
    ));
    f.render_widget(Paragraph::new(visible).block(chat_block), chunks[0]);

    let input_block =
        Block::default()
            .borders(Borders::ALL)
            .title(if running { "busy" } else { "input" });
    f.render_widget(
        Paragraph::new(input.buffer.clone()).block(input_block),
        chunks[1],
    );

    let status_style = if running {
        Style::default().fg(Color::Yellow)
    } else if status == "error" {
        Style::default().fg(Color::Red)
    } else {
        Style::default().fg(Color::Green)
    };
    f.render_widget(
        Paragraph::new(Line::from(Span::styled(status, status_style))),
        chunks[2],
    );

    if let Some(d) = dialog {
        render_dialog(f, d);
    }
}

/// Renders the active dialog centered.
fn render_dialog(f: &mut ratatui::Frame<'_>, d: &DialogState) {
    let area = centered_rect(60, 40, f.area());
    let mut text = vec![Line::from(d.body())];
    if matches!(
        d.kind,
        Dialog::Password { .. }
            | Dialog::Ask {
                is_approval: false,
                ..
            }
    ) {
        text.push(Line::from(Span::styled(
            if matches!(d.kind, Dialog::Password { .. }) {
                "•".repeat(d.editor.buffer.len())
            } else {
                d.editor.buffer.clone()
            },
            Style::default().fg(Color::Cyan),
        )));
    }
    f.render_widget(
        Paragraph::new(text).block(Block::default().borders(Borders::ALL).title(d.title())),
        area,
    );
}

/// A centered rect for dialogs.
fn centered_rect(percent_x: u16, percent_y: u16, area: Rect) -> Rect {
    let popup = Layout::vertical([
        Constraint::Percentage((100 - percent_y) / 2),
        Constraint::Percentage(percent_y),
        Constraint::Percentage((100 - percent_y) / 2),
    ])
    .split(area);
    Layout::horizontal([
        Constraint::Percentage((100 - percent_x) / 2),
        Constraint::Percentage(percent_x),
        Constraint::Percentage((100 - percent_x) / 2),
    ])
    .split(popup[1])[1]
}
