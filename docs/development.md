# Development

## Installation

```bash
# Install in development mode
make install-dev

# Run tests
make test
```

## Benchmarks

- Basic benchmark harness: `python scripts/benchmarks/basic_benchmark.py --iterations 50`

## Architecture

```
src/agentframework/
├── agent.py          # Main agent logic
├── chat.py          # Interactive chat interface
├── cli.py           # CLI for single commands
├── providers/      # LLM provider implementations
│   └── ollama.py    # Ollama provider
├── safety.py        # Security validation
├── session.py      # Chat session management
└── tools/          # Tool implementations
    ├── bash.py
    ├── file.py
    ├── web.py
    ├── git.py
    ├── search.py
    ├── memory.py
    └── notes.py
```
