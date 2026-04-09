import { memo, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Pencil, Copy, Check } from 'lucide-react';
import { useChat } from '../context';

export const MessageList = memo(function MessageList() {
  const { messages, isStreaming, editMessage } = useChat();
  const containerRef = useRef<HTMLDivElement>(null);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editText, setEditText] = useState('');
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

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
                            <pre className="tool-result-content">
                              {tc.result.content || tc.result.error || '(empty)'}
                            </pre>
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
                  className="icon-button"
                  onClick={() => {
                    navigator.clipboard.writeText(msg.content);
                    setCopiedIndex(idx);
                    setTimeout(() => setCopiedIndex(null), 2000);
                  }}
                  title="Copy"
                >
                  {copiedIndex === idx ? <Check size={16} /> : <Copy size={16} />}
                </button>
              )}
              {msg.role === 'user' && !isStreaming && (
                <button
                  className="icon-button"
                  onClick={() => { setEditingIndex(idx); setEditText(msg.content); }}
                  title="Edit"
                >
                  <Pencil size={16} />
                </button>
              )}
            </div>
            {editingIndex === idx && (
              <div className="edit-overlay">
                <textarea
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  autoFocus
                  rows={3}
                />
                <div className="edit-actions">
                  <button 
                    onClick={() => {
                      editMessage(idx, editText);
                      setEditingIndex(null);
                    }}
                  >
                    Regenerate
                  </button>
                  <button onClick={() => setEditingIndex(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
});
// test
