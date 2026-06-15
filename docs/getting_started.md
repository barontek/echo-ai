# Getting Started

## Configuration

Edit `config.yaml`:

```yaml
model:
  provider: ollama
  name: gemma4:e4b
  base_url: http://localhost:11434
  temperature: 0.1
  num_ctx: 32768

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
    - humanizer
    - deep_search
```

### Recommended Models

| Model | Description |
|-------|-------------|
| `gemma4:e4b` | Best for following instructions and tool calling (default) |
| `qwen3:4b-instruct` | Strong instruction following |
| `qwen3:4b` | General purpose with reasoning |
| `llama3.2` | Meta's lightweight model |

## Requirements

- Python 3.11+
- Ollama (for local models) or API keys for Anthropic/OpenAI
