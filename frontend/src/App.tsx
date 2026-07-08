import { useState, useEffect } from 'react';
import { api } from './api/client';
import { ChatProvider } from './context';
import { ApprovalDialog, Header, Sidebar, MessageList, ChatInput, UnlockScreen, SetupScreen } from './components';
import './App.css';

function App() {
  const [statusLoading, setStatusLoading] = useState(true);
  const [locked, setLocked] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    api.getStatus()
      .then((s) => {
        setLocked(s.locked);
        setNeedsSetup(s.needs_setup);
      })
      .catch(() => setLocked(true))
      .finally(() => setStatusLoading(false));
  }, []);

  if (statusLoading) {
    return <div className="app-loading">Loading…</div>;
  }

  if (needsSetup) {
    return <SetupScreen onComplete={() => { setNeedsSetup(false); setLocked(false); }} />;
  }

  if (locked) {
    return <UnlockScreen onUnlocked={() => setLocked(false)} />;
  }

  return (
    <ChatProvider>
      <ApprovalDialog />
      <div className="app">
        <Sidebar />
        <div className="main-content">
          <Header />
          <MessageList />
          <ChatInput />
        </div>
      </div>
    </ChatProvider>
  );
}

export default App;
