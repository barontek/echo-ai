# echo-ai-tui

The `--cli` terminal interface: ratatui + crossterm, replacing the C
project's notcurses TUI. UI models (input, chat buffer, keymap, command
registry, stream classifier, markdown) stay pure and testable without a
terminal; the render layer is a thin adapter over them.

## Module map

| Module | Responsibility |
|---|---|
| `shell` | app lifecycle, layout, poll loop |
| `worker` | agent execution task + event ring |
| `models` | input, chat, keys, command, dialogs, stream, markdown, tool_args, theme |
| `stores` | model/prompt/session `JSON`-backed stores |
| `render` | ratatui draw calls |

## Testing

Ported `test_tui_*` suites run headless (models only); the event ring is
`loom`-tested.