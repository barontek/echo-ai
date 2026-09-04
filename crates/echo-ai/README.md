# echo-ai

The `echo-ai` binary: CLI entry point and mode dispatcher. Parses `--web` (default), `--cli`, `--config`,
`--debug`, `--help` and hands control to `echo-ai-server` or
`echo-ai-tui`.