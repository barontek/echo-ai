import { memo, useState, useEffect } from 'react';
import { useChat } from '../context';

interface DebugPanelProps {
  isOpen?: boolean;
}

export const DebugPanel = memo(function DebugPanel({ isOpen = false }: DebugPanelProps) {
  const [logs, setLogs] = useState<string[]>([]);
  const [isExpanded, setIsExpanded] = useState(isOpen);
  const chat = useChat();

  useEffect(() => {
    // Capture console.log for debugging
    const originalLog = console.log;
    const originalError = console.error;

    const logs: string[] = [];

    console.log = (...args) => {
      const msg = args
        .map((a) => (typeof a === 'object' ? JSON.stringify(a) : String(a)))
        .join(' ');
      logs.push(`[LOG] ${msg}`);
      setLogs([...logs].slice(-50)); // Keep last 50 logs
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

  if (!isExpanded) {
    return (
      <button
        className="debug-toggle"
        onClick={() => setIsExpanded(true)}
        style={{
          position: 'fixed',
          bottom: '10px',
          right: '10px',
          padding: '8px 12px',
          background: '#ff6b6b',
          color: 'white',
          border: 'none',
          borderRadius: '4px',
          cursor: 'pointer',
          fontSize: '12px',
          zIndex: 9999,
        }}
      >
        🐛 Debug
      </button>
    );
  }

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '10px',
        right: '10px',
        width: '400px',
        maxHeight: '300px',
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
        <strong>🐛 Debug Panel</strong>
        <button
          onClick={() => setIsExpanded(false)}
          style={{ background: 'transparent', border: 'none', color: '#fff', cursor: 'pointer' }}
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
  );
});
