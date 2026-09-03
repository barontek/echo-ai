# echo-ai

The `echo-ai` binary: CLI entry point and mode dispatcher (mirrors
`~/echo-ai-c/src/main.c`). Parses `--web` (default), `--cli`, `--config`,
`--debug`, `--help` and hands control to `echo-ai-server` or
`echo-ai-tui`. The C version's `--chat` REPL is not ported.