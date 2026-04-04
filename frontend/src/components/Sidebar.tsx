import { memo, useState } from 'react';
import { useChat } from '../context';

export const Sidebar = memo(function Sidebar() {
  const { sessions, activeSessionId, models, currentModel, selectSession, createSession, selectModel, deleteSession, sidebarOpen, setSidebarOpen } = useChat();
  const [searchTerm, setSearchTerm] = useState('');
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const filteredSessions = sessions.filter(s =>
    s.title?.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleDelete = (sessionId: string) => {
    deleteSession(sessionId);
    setDeleteConfirm(null);
  };

  const handleSelectSession = (id: string) => {
    selectSession(id);
    setSidebarOpen(false);
  };

  return (
    <>
      {sidebarOpen && <div className="sidebar-overlay" onClick={() => setSidebarOpen(false)} />}
      <div className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
      <div className="sidebar-header">
        <h2>Echo AI</h2>
      </div>

      <div className="model-selector">
        <button
          className="model-button"
          onClick={() => setShowModelDropdown(!showModelDropdown)}
        >
          <span className="model-name">{currentModel}</span>
          <span className="dropdown-arrow">▼</span>
        </button>
        {showModelDropdown && (
          <div className="model-dropdown">
            {models.map(m => (
              <button
                key={m}
                className={`model-option ${m === currentModel ? 'active' : ''}`}
                onClick={() => { selectModel(m); setShowModelDropdown(false); }}
              >
                {m}
              </button>
            ))}
          </div>
        )}
      </div>

      <button className="new-chat-button" onClick={createSession}>
        <span>+</span> New Chat
      </button>

      <div className="search-container">
        <input
          type="text"
          className="search-input"
          placeholder="Search conversations..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      <div className="sessions-list">
        {filteredSessions.map(session => (
          <div
            key={session.id}
            className={`session-item ${session.id === activeSessionId ? 'active' : ''}`}
            onClick={() => selectSession(session.id)}
          >
            <span className="session-title">{session.title || 'New Chat'}</span>
            <button
              className="delete-button"
              onClick={(e) => { e.stopPropagation(); setDeleteConfirm(session.id); }}
            >
              ×
            </button>
          </div>
        ))}
        {filteredSessions.length === 0 && sessions.length > 0 && (
          <div className="empty-state" style={{ padding: '20px', fontSize: '13px' }}>
            No matching conversations
          </div>
        )}
      </div>

      {deleteConfirm && (
        <div className="confirm-overlay" onClick={() => setDeleteConfirm(null)}>
          <div className="confirm-dialog" onClick={e => e.stopPropagation()}>
            <p>Delete this conversation?</p>
            <div className="confirm-actions">
              <button className="confirm-cancel" onClick={() => setDeleteConfirm(null)}>Cancel</button>
              <button className="confirm-delete" onClick={() => handleDelete(deleteConfirm)}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});
