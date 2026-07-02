import { ChatProvider } from './context';
import { ApprovalDialog, Header, Sidebar, MessageList, ChatInput } from './components';
import './App.css';

function App() {
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
