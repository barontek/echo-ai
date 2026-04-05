import { memo, useState, useEffect } from 'react';
import { useChat } from '../context';

export const Header = memo(function Header() {
  const { currentModel, messages, connectionStatus, sidebarOpen, setSidebarOpen } = useChat();
  const [logs, setLogs] = useState<string[]>([]);
  const [showDebug, setShowDebug] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('theme') as 'dark' | 'light') || 'dark';
  });

  const toggleTheme = () => {
    setTheme((prev) => {
      const newTheme = prev === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', newTheme);
      localStorage.setItem('theme', newTheme);
      return newTheme;
    });
  };

  // Sync theme on mount
  useEffect(() => {
    const saved = localStorage.getItem('theme') as 'dark' | 'light' | null;
    if (saved) {
      setTheme(saved);
      document.documentElement.setAttribute('data-theme', saved);
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
    }
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => {
      const newTheme = prev === 'dark' ? 'light' : 'dark';
      return newTheme;
    });
  };

  const statusText = {
    connected: 'Connected',
    connecting: 'Connecting...',
    disconnected: 'Disconnected',
    reconnecting: 'Reconnecting...',
  }[connectionStatus];

  useEffect(() => {
    const originalLog = console.log;
    const originalError = console.error;
    const logs: string[] = [];

    console.log = (...args) => {
      const msg = args
        .map((a) => (typeof a === 'object' ? JSON.stringify(a) : String(a)))
        .join(' ');
      logs.push(`[LOG] ${msg}`);
      setLogs([...logs].slice(-50));
      originalLog.apply(console, args);
    };

    console.error = (...args) => {
      const msg = args
        .map((a) => (typeof a === 'object' ? JSON.stringify(a) : String(a)))
        .join(' ');
      logs.push(`[ERR] ${msg}`);
      setLogs([...logs].slice(-50));
      originalError.apply(console, args);
    };

    return () => {
      console.log = originalLog;
      console.error = originalError;
    };
  }, []);

  const chat = useChat();

  return (
    <>
      <div className="chat-header">
        <div className="header-left">
          <button className="menu-button" onClick={() => setSidebarOpen(!sidebarOpen)}>
            Menu
          </button>
          <span className="model-badge">{currentModel}</span>
        </div>
        <div className="header-right">
          <button
            onClick={toggleTheme}
            style={{
              background: 'transparent',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              padding: '6px 10px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            {theme === 'dark' ? 'Light' : 'Dark'}
          </button>
          <button
            onClick={() => setShowDebug(!showDebug)}
            style={{
              background: 'transparent',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              padding: '6px 10px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            Debug
          </button>
          <div className="connection-status">
            <span
              className={`status-dot ${connectionStatus === 'connected' ? '' : 'disconnected'}`}
            ></span>
            <span>{statusText}</span>
          </div>
          <span className="message-count">
            {messages.length > 0 ? `${messages.length} messages` : 'New chat'}
          </span>
        </div>
      </div>
      {showDebug && (
        <div
          style={{
            position: 'absolute',
            top: '60px',
            right: '20px',
            width: '350px',
            maxHeight: '280px',
            background: '#1a1a2e',
            border: '1px solid #444',
            borderRadius: '8px',
            padding: '12px',
            fontSize: '11px',
            fontFamily: 'monospace',
            color: '#eee',
            zIndex: 9999,
            overflow: 'auto',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
            <strong>Debug Panel</strong>
            <button
              onClick={() => setShowDebug(false)}
              style={{
                background: 'transparent',
                border: 'none',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              ✕
            </button>
          </div>
          <div style={{ marginBottom: '8px' }}>
            <strong>State:</strong>
            <pre style={{ margin: '4px 0', fontSize: '10px', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(
                {
                  isConnected: chat.isConnected,
                  isStreaming: chat.isStreaming,
                  sessionId: chat.activeSessionId,
                  messages: chat.messages.length,
                  model: chat.currentModel,
                },
                null,
                2
              )}
            </pre>
          </div>
          <div style={{ marginBottom: '8px' }}>
            <strong>Messages:</strong>
            {chat.messages.map((m, i) => (
              <div
                key={i}
                style={{
                  margin: '2px 0',
                  padding: '2px',
                  background: m.role === 'user' ? '#2d2d44' : '#1f1f35',
                }}
              >
                {m.role}: {m.content.substring(0, 30)}...
              </div>
            ))}
          </div>
          <div>
            <strong>Recent Logs:</strong>
            {logs.slice(-10).map((log, i) => (
              <div
                key={i}
                style={{
                  margin: '2px 0',
                  color: log.includes('[ERR]') ? '#ff6b6b' : '#888',
                  fontSize: '9px',
                }}
              >
                {log}
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
});
