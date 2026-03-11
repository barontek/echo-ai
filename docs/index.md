# Echo AI

A standalone AI agent framework built from scratch, similar to OpenCode but simpler.

## Features

- **Multiple LLM Providers**: Anthropic, OpenAI, Ollama
- **Tool Calling**: bash, read/write files, list directories, glob, grep, web fetch, web search, git, memory, notes
- **Safety**: Workspace confinement, command allowlisting, dangerous pattern blocking
- **Sessions**: Save/load conversations, undo file changes
- **Chat Mode**: Interactive continuous conversation with command history

## Quick Start

```bash
# Clone and setup
git clone https://github.com/barontek/echo-ai.git
cd echo-ai
make install

# Run in chat mode (continuous conversation)
./chat

# Or run single command
./agent "your task"
```

## Project Status

- **Maturity**: Beta-quality, fast-moving standalone agent framework
- **Supported providers**: Ollama, Anthropic, OpenAI
- **Known limitations**:
  - Terminal/chat runtime is still being modularized
  - Some advanced observability and CI quality gates are still evolving
- **Near-term roadmap**:
  - Unified runtime/config bootstrap across entrypoints
  - Stronger integration scenarios and contributor verify workflow
  - Improved structured debug telemetry
