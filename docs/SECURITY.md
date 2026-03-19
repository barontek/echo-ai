# Security Policy

## Reporting Security Issues

If you discover a security vulnerability, please report it privately:

1. **Do NOT** open a public GitHub issue
2. Email the maintainers directly
3. Include details about the vulnerability
4. Allow time for a fix before public disclosure

## Security Model

### What Echo AI Protects Against

| Threat | Protection | Location |
|--------|------------|----------|
| Path Traversal | Validates all file paths | `safety.py` |
| Command Injection | Sanitizes bash commands | `tools/bash.py` |
| Prompt Injection | Input validation | `safety.py` |
| Rate Limiting | Request throttling | `web_api.py` |

### Path Traversal Prevention

All file operations are validated:

```python
def check_path_traversal(self, path: str) -> bool:
    """Check for path traversal attempts."""
    resolved = Path(path).resolve()
    # Must be within allowed directory
    return str(resolved).startswith(str(self.allowed_dir))
```

Blocked patterns:
- `../../etc/passwd`
- `/absolute/../path`
- `path/with/../escape`
- Symbolic links to outside directories

### Command Injection Prevention

Bash commands are sanitized:

```python
# Blocked characters in user input
BLOCKED_CHARS = [';', '|', '&', '$', '`', '\n', '\r']
```

Allowed only:
- Simple alphanumeric commands
- Common flags (--help, -v, etc.)
- Quoted arguments

### Rate Limiting

- 60 requests per minute per IP
- Applied to `/api/chat` endpoint
- Returns 429 when exceeded

## Security Configuration

### CORS Settings

Configure allowed origins in `config.yaml`:

```yaml
web:
  cors_origins:
    - "https://yourdomain.com"
    - "http://localhost:3000"  # Development only
  cors_allow_credentials: true
```

**Never use** `allow_origins=["*"]` in production.

### API Keys

For OpenAI integration, use environment variables:

```bash
export OPENAI_API_KEY="sk-..."
```

Never commit API keys to version control.

## Best Practices

### Deployment

1. **Run as non-root user**
   ```dockerfile
   RUN adduser -S appuser
   USER appuser
   ```

2. **Use read-only filesystem where possible**

3. **Enable HTTPS** via reverse proxy

4. **Regular backups** of session database

### Development

1. Never log sensitive data (API keys, passwords)
2. Validate all user input
3. Use parameterized queries (SQLite does this by default)
4. Keep dependencies updated

## Known Limitations

### Browser-Side

- WebSocket connections are not encrypted (use HTTPS)
- LocalStorage stores session IDs in plain text

### Model-Generated Content

Echo AI does **not** filter model outputs. Be cautious when:
- Displaying untrusted content
- Using with vulnerable user groups
- Running in sensitive environments

### Session Data

- Sessions stored in unencrypted SQLite database
- Not suitable for highly sensitive data
- Consider encryption at rest for production

## Compliance

### Data Handling

- Session data stored locally only
- No external data transmission (except to Ollama/OpenAI)
- User can delete all sessions via UI or API

### Logging

- Correlation IDs for audit trails
- No PII logging by default
- Logs can contain message content (not API keys)

## Version Support

| Version | Security Updates |
|---------|-----------------|
| Latest | ✅ Full support |
| 1.x | ❌ Unsupported |

Update regularly for security patches.
