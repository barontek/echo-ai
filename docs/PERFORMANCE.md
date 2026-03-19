# Performance Tuning Guide

Optimizing Echo AI for different workloads.

## Quick Wins

### 1. Enable Response Caching

```yaml
# config.yaml
cache:
  enabled: true
  ttl_seconds: 3600
```

### 2. Pre-load Model

```bash
# Before starting Echo AI
ollama pull qwen3:4b-instruct
```

### 3. Adjust Context Window

```yaml
# config.yaml
agent:
  max_history_messages: 20  # Reduce for shorter context
```

## Bottlenecks and Solutions

### Token Counting

**Problem:** Encoder recreated on every call

**Solution:** ✅ Already fixed - encoder is cached at module level

```python
# src/agentframework/conversation.py
_encoder = tiktoken.get_encoding("cl100k_base")  # Cached

def estimate_tokens(text: str) -> int:
    return len(_encoder.encode(text))
```

### Message Filtering

**Problem:** Regex patterns recompiled per message

**Solution:** ✅ Already fixed - patterns pre-compiled

```python
# src/agentframework/web_api.py
_INTERNAL_PATTERNS = [
    re.compile(r"System Note: Tools executed"),
    re.compile(r"Tool '.*' returned:"),
    ...
]
```

### Database Queries

**Problem:** No pagination on session list

**Current:** Loads all sessions, sorts in Python

**Improvement:** Add pagination

```python
# Recommended for large session counts
def list_sessions(self, limit: int = 100, offset: int = 0):
    query = (
        db.query(DBSessionModel)
        .order_by(DBSessionModel.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
```

### Frontend Rendering

**Problem:** All messages re-rendered on state change

**Solution:** ✅ Already fixed - virtual window of 120 messages

```javascript
// Only render visible window
const windowSize = 120;
const visibleMessages = messages.slice(-windowSize);
```

## Memory Optimization

### Reduce Model Size

Smaller models use less RAM:

```
qwen3:1.7b-instruct  ~1GB
qwen3:4b-instruct    ~2.5GB
qwen3:8b-instruct    ~5GB
qwen3:14b-instruct   ~9GB
```

### Limit History

```yaml
# config.yaml
agent:
  max_history_messages: 10  # Keep conversations short
```

### Clear Sessions

```bash
# Purge sessions older than 30 days
curl -X POST http://localhost:8000/api/sessions/purge?days=30
```

## Latency Optimization

### Network

| Component | Latency | Improvement |
|-----------|---------|-------------|
| Ollama localhost | ~50ms | Already optimal |
| Ollama remote | ~200ms | Use local if possible |
| WebSocket | ~10ms | Already optimal |

### Ollama Settings

```bash
# Use GPU acceleration
OLLAMA_NUM_PARALLEL=4 ollama serve

# Increase context window
ollama run qwen3:4b-instruct /set parameter.num_ctx 4096
```

### Streaming vs Non-Streaming

| Use Case | Method | Why |
|----------|--------|-----|
| Real-time UI | WebSocket | Shows tokens as they arrive |
| API integrations | REST `/api/chat` | Simpler code |
| Background tasks | REST | No connection maintenance |

## Concurrent Users

### Single Instance

Tested up to 10 concurrent WebSocket connections.

### Multi-Instance (Future)

For >10 users, scale horizontally:

```
                    ┌─────────────────┐
                    │   Load Balancer  │
                    └────────┬────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
    ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
    │  Instance  │    │  Instance  │    │  Instance  │
    │     1      │    │     2      │    │     3      │
    └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                    ┌────────▼────────┐
                    │   Redis (Future) │
                    │  Session Store   │
                    └─────────────────┘
```

### Current Limitations

- Sessions stored in local SQLite
- Cannot share sessions across instances
- Requires sticky sessions or session affinity

## Monitoring

### Key Metrics

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Response time | <2s | 2-5s | >5s |
| Memory usage | <70% | 70-90% | >90% |
| CPU usage | <50% | 50-80% | >80% |

### Check Logs

```bash
# Find slow responses
grep -E "(slow|timeout)" logs/app.log

# Check error rate
grep -c "ERROR" logs/app.log
```

## Profiling

### Python Profiler

```python
# Add to code temporarily
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# ... your code ...

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

### Memory Profiler

```bash
pip install memory_profiler
mprof run python -m uvicorn src.agentframework.web_api:app
mprof plot
```

## Benchmarking

### Simple Load Test

```bash
# Using wrk
wrk -t4 -c100 -d30s http://localhost:8000/health

# Using Apache Bench
ab -n 1000 -c 10 http://localhost:8000/health
```

### WebSocket Test

```javascript
// Example using wscat
npm install -g wscat
wscat -c ws://localhost:8000/ws/chat -s 10  # 10 concurrent connections
```

## Summary Checklist

- [x] Cached tiktoken encoder
- [x] Pre-compiled regex patterns
- [x] Message window (120 max)
- [ ] Database indexes
- [ ] Redis for session sharing
- [ ] Prometheus metrics
