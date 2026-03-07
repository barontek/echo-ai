# Getting Started

## Configuration

Edit `config.yaml`:

```yaml
model:
  provider: ollama      # anthropic, openai, or ollama
  name: qwen3:4b-instruct  # default model
  base_url: http://localhost:11434
  temperature: 0.1

tools:
  enabled:
    - bash
    - read_file
    - write_file
    - list_dir
    - glob
    - grep
    - git
    - web_fetch
    - web_search
    - memory
    - notes
```

### Recommended Models

| Model | Description |
|-------|-------------|
| `qwen3:4b-instruct` | Best for following instructions (default) |
| `qwen2.5-coder:3b` | Best for strict tool calling and coding |
| `qwen3:4b` | General purpose with strong reasoning |
| `llama3.2` | Meta's lightweight model |
| `phi3.5` | Microsoft's highly stable model |

## Requirements

- Python 3.11+
- Ollama (for local models) or API keys for Anthropic/OpenAI
