# Vibe AI

A standalone AI agent framework built from scratch, similar to OpenCode but simpler.

## Features

- 🤖 **Multiple LLM Providers**: Anthropic, OpenAI, Ollama
- 🔧 **Tool Calling**: bash, read/write files, glob, grep, git, web fetch
- 🛡️ **Safety**: Workspace confinement, command allowlisting, dangerous pattern blocking
- 💾 **Sessions**: Save/load conversations, undo file changes
- 💬 **Chat Mode**: Interactive continuous conversation

## Quick Start

```bash
# Clone and setup
git clone https://github.com/barontek/vibe-ai.git
cd vibe-ai
make install

# Run in chat mode (continuous conversation)
./chat

# Or run single command
./agent "your task"
```

## Configuration

Edit `config.yaml`:

```yaml
model:
  provider: ollama      # anthropic, openai, or ollama
  name: qwen2.5:3b      # model name
  base_url: http://localhost:11434

tools:
  enabled:
    - bash
    - read_file
    - write_file
    - list_dir
    - glob
    - grep
    - git
```

## Commands

Chat mode:
- `/new` - Start new chat
- `/save name` - Save chat
- `/load name` - Load saved chat
- `/chats` - List chats
- `/undo` - Undo file change
- `/redo` - Redo file change
- `/exit` - Exit

## Safety

- Workspace confinement (files outside workspace blocked)
- Command allowlisting
- Dangerous pattern blocking (rm -rf, curl|sh, etc.)
- Approval prompts for sensitive operations
- Network access controls

## Requirements

- Python 3.11+
- Ollama (for local models) or API keys for Anthropic/OpenAI
