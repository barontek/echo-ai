import { ChatProvider } from './context';
import { Header, Sidebar, MessageList, ChatInput } from './components';
import './App.css';

function App() {
  return (
    <ChatProvider>
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
