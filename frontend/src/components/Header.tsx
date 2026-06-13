import { memo, useState } from 'react';
import { useChat } from '../context';

function getInitialTheme(): 'dark' | 'light' {
  const saved = localStorage.getItem('theme');
  if (saved === 'light' || saved === 'dark') {
    document.documentElement.setAttribute('data-theme', saved);
    return saved;
  }
  return 'dark';
}

export const Header = memo(function Header() {
  const chat = useChat();
  const [showDebug, setShowDebug] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(getInitialTheme);

  const toggleTheme = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
  };

  const statusText = {
    connected: 'Connected',
    connecting: 'Connecting...',
    disconnected: 'Disconnected',
    reconnecting: 'Reconnecting...',
  }[chat.connectionStatus];

  return (
    <>
      <div className="chat-header">
        <div className="header-left">
          <button className="menu-button" onClick={() => chat.setSidebarOpen(!chat.sidebarOpen)}>
            Menu
          </button>
          <span className="model-badge">{chat.currentModel}</span>
        </div>
        <div className="header-right">
          <div className="connection-status">
            <span
              className={`status-dot ${chat.connectionStatus === 'connected' ? '' : 'disconnected'}`}
            ></span>
            <span>{statusText}</span>
          </div>
          <button
            className="header-icon-btn"
            onClick={toggleTheme}
            title="Toggle theme"
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
          <button
            className="header-icon-btn"
            onClick={() => setShowDebug(!showDebug)}
            title="Debug"
          >
            ⚙
          </button>
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
            background: 'var(--bg-secondary)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            padding: '12px',
            fontSize: '11px',
            fontFamily: 'monospace',
            color: 'var(--text-primary)',
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
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              x
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
          <div>
            <strong>Recent Logs:</strong>
            <div style={{ color: 'var(--text-muted)', fontSize: '9px' }}>Enable debug logging</div>
          </div>
        </div>
      )}
    </>
  );
});
