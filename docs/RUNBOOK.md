# Echo AI Runbook

Operations guide for deploying and maintaining Echo AI.

## Quick Start

```bash
# Start the server
source .venv/bin/activate
python -m uvicorn src.agentframework.web_api:app --host 0.0.0.0 --port 8000 --reload

# Or use the CLI
source .venv/bin/activate
echo-ai
```

## Deployment

### Prerequisites

- Python 3.11+
- Ollama server (for local models)
- SQLite support

### Docker

```bash
# Build image
docker build -t echo-ai .

# Run container with resource limits
docker run -p 8000:8000 \
  --memory=512m \
  --cpus=1.0 \
  -v $(pwd)/sessions:/app/.echo-ai/sessions \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  echo-ai
```

### Docker Compose (Recommended)

```bash
# Start with docker-compose (includes resource limits)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

Resource limits:
- CPU: 1 core max
- Memory: 512MB max

### Systemd Service

```ini
# /etc/systemd/system/echo-ai.service
[Unit]
Description=Echo AI Agent
After=network.target

[Service]
Type=simple
User=echo-ai
WorkingDirectory=/opt/echo-ai
ExecStart=/opt/echo-ai/.venv/bin/python -m uvicorn src.agentframework.web_api:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable echo-ai
sudo systemctl start echo-ai
sudo systemctl status echo-ai
```

## Configuration

Edit `config.yaml`:

```yaml
agent:
  model: "qwen3:4b-instruct"
  max_iterations: 20
  temperature: 0.3

server:
  host: "0.0.0.0"
  port: 8000

observability:
  otel_enabled: false
  console_export: true

web:
  cors_origins:
    - "http://localhost:3000"
```

## Monitoring

### Health Check

```bash
curl http://localhost:8000/health
# {"status": "healthy", "service": "echo-ai", "timestamp": "..."}
```

### Logs

```bash
# View recent logs
tail -f logs/app.log

# Search for errors
grep -i error logs/app.log

# View by correlation ID
grep "req-123" logs/app.log
```

### Metrics

If Prometheus metrics are enabled:

```bash
curl http://localhost:8000/metrics
```

## Common Issues

### Ollama Not Running

**Error:** "Connection refused" when connecting to Ollama

**Fix:**
```bash
# Start Ollama
ollama serve

# Or check if it's running
ps aux | grep ollama
```

### Session Database Locked

**Error:** "database is locked"

**Fix:**
```bash
# Kill any stuck processes
pkill -f "sqlite.*agent_sessions"

# Or restart the service
sudo systemctl restart echo-ai
```

### Out of Memory

**Error:** Memory errors during long conversations

**Fix:**
- Reduce `max_history_messages` in config
- Use a smaller model
- Restart the service to clear memory

### Rate Limited

**Error:** "429 Too Many Requests"

**Fix:**
- Wait 60 seconds
- Check if another client is making requests
- Adjust rate limit in config

## Backup and Restore

### Backup Sessions

```bash
# Backup the SQLite database
cp ~/.echo-ai/sessions/agent_sessions.db /backup/sessions-$(date +%Y%m%d).db

# Or use sqlite3
sqlite3 ~/.echo-ai/sessions/agent_sessions.db ".backup /backup/sessions.db"
```

### Restore Sessions

```bash
# Stop the service
sudo systemctl stop echo-ai

# Restore from backup
cp /backup/sessions.db ~/.echo-ai/sessions/agent_sessions.db

# Restart
sudo systemctl start echo-ai
```

### Export to JSON

```bash
python3 -c "
import sqlite3
import json

conn = sqlite3.connect('~/.echo-ai/sessions/agent_sessions.db')
cursor = conn.execute('SELECT id, title, messages FROM agent_sessions')
sessions = []
for row in cursor:
    sessions.append({'id': row[0], 'title': row[1], 'messages': row[2]})
print(json.dumps(sessions, indent=2))
" > sessions.json
```

## Security

### Change Permissions

```bash
# Make session directory readable only by app user
chmod 700 ~/.echo-ai/sessions
chmod 600 ~/.echo-ai/sessions/agent_sessions.db
```

### Enable HTTPS

Use a reverse proxy:

```nginx
# /etc/nginx/sites-available/echo-ai
server {
    listen 443 ssl;
    server_name echo-ai.example.com;

    ssl_certificate /etc/ssl/certs/echo-ai.crt;
    ssl_certificate_key /etc/ssl/private/echo-ai.key;

    location / {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
    }
}
```

## Performance Tuning

### Increase Worker Processes

```bash
# Multiple workers for production
uvicorn src.agentframework.web_api:app --workers 4
```

### Enable Redis (Future)

For scaling to multiple instances, configure Redis for session storage.

## Support

- Issues: https://github.com/barontek/echo-ai/issues
- Documentation: https://github.com/barontek/echo-ai/wiki
