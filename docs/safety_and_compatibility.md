# Safety & Compatibility

## Safety Features

Echo AI includes several safety mechanisms to ensure secure operation:

- **Workspace confinement**: Files outside the workspace are blocked
- **Command allowlisting**: Only permitted commands can be executed
- **Dangerous pattern blocking**: Blocks harmful commands like `rm -rf`, `curl|sh`, etc.
- **Approval prompts**: Prompts for user approval before sensitive operations
- **Network access controls**: Limits unauthorized network access

## Compatibility Policy

- **Python**: 3.11+ is required at runtime.
- **Providers**:
  - `ollama` works without cloud API keys (requires local Ollama server).
  - `anthropic` requires `ANTHROPIC_API_KEY`.
  - `openai` requires `OPENAI_API_KEY`.
- **Tooling**: `make verify` is the baseline quality gate for local and CI checks.

## Troubleshooting

- **Error: Python 3.11+ is required**
  - Use `python3.11` (or newer) and recreate your environment.
- **Provider key errors for Anthropic/OpenAI**
  - Export the required key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) or switch to `ollama`.
- **Ollama connection failures**
  - Ensure Ollama is running and `model.base_url` in `config.yaml` is correct.
- **Need full diagnostics**
  - Run with `--debug` for detailed logs, or `--debug-json` for machine-readable logs.
