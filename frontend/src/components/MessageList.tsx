import { memo, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { useChat } from '../context';

export const MessageList = memo(function MessageList() {
  const { messages, isStreaming, currentThinking } = useChat();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, isStreaming, currentThinking]);

  return (
    <div className="message-list" ref={containerRef}>
      {messages.length === 0 && !isStreaming && (
        <div className="empty-state">
          <p>Start a conversation...</p>
        </div>
      )}

      {messages.map((msg, idx) => (
        <div key={`${msg.timestamp}-${idx}`} className={`message message-${msg.role}`}>
          <div className="message-role">{msg.role === 'user' ? 'You' : 'AI'}</div>
          <div className="message-bubble">
            <div className="message-content">
              {msg.thinking && (
                <div className="thinking">
                  <span className="thinking-label">Thinking</span>
                  <ReactMarkdown>{msg.thinking}</ReactMarkdown>
                </div>
              )}
              {msg.content && <ReactMarkdown>{msg.content}</ReactMarkdown>}
              {msg.has_tools && msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="tool-calls">
                  {msg.tool_calls.map((tc, i) => {
                    const entries = Object.entries(tc.arguments);
                    const argsDisplay = entries.map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join('\n');
                    return (
                      <details key={i} className="tool-call">
                        <summary className="tool-name">{tc.name}</summary>
                        <pre className="tool-args">{argsDisplay}</pre>
                      </details>
                    );
                  })}
                </div>
              )}
              {msg.error && <div className="message-error">{msg.error}</div>}
            </div>
            <div className="message-footer">
              {msg.timestamp && <div className="message-time">{msg.timestamp}</div>}
              {msg.role === 'assistant' && msg.content && (
                <button
                  className="copy-button"
                  onClick={() => navigator.clipboard.writeText(msg.content)}
                  title="Copy"
                >
                  Copy
                </button>
              )}
            </div>
          </div>
        </div>
      ))}

      {isStreaming && currentThinking && (
        <div className="message message-assistant streaming">
          <div className="message-role">AI</div>
          <div className="message-bubble">
            <div className="message-content">
              <div className="thinking">
                <span className="thinking-label">Thinking</span>
                <ReactMarkdown>{currentThinking}</ReactMarkdown>
              </div>
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});
// test
