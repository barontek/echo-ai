import { memo, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChat } from '../context';

export const MessageList = memo(function MessageList() {
  const { messages, isStreaming } = useChat();
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, isStreaming]);

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
                <details className="thinking-collapsible">
                  <summary className="thinking-label">Thinking</summary>
                  <div className="markdown-content">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.thinking}</ReactMarkdown>
                  </div>
                </details>
              )}
              {msg.content && (
                <div className="markdown-content">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                </div>
              )}
              {msg.has_tools && msg.tool_calls && msg.tool_calls.length > 0 && (
                <div className="tool-calls">
                  {msg.tool_calls.map((tc, i) => {
                    const entries = Object.entries(tc.arguments);
                    const argsDisplay = entries
                      .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                      .join('\n');
                    return (
                      <details key={i} className="tool-call">
                        <summary className="tool-name">{tc.name}</summary>
                        <pre className="tool-args">{argsDisplay}</pre>
                        {tc.result && (
                          <div className="tool-result">
                            <div className="tool-result-label">Result:</div>
                            <pre className="tool-result-content">{tc.result.content || tc.result.error || '(empty)'}</pre>
                          </div>
                        )}
                      </details>
                    );
                  })}
                </div>
              )}
              {msg.error && <div className="message-error">{msg.error}</div>}
              {isStreaming && idx === messages.length - 1 && msg.role === 'assistant' && (
                <div className="typing-indicator">
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              )}
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
    </div>
  );
});
// test
