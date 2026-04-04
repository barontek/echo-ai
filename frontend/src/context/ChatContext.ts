import { createContext, type Context } from 'react';

export interface ChatContextValue {
  sessions: Array<{ id: string; title: string; created_at: string }>;
  activeSessionId: string | null;
  currentModel: string;
  models: string[];
  messages: Array<{
    role: 'user' | 'assistant';
    content: string;
    timestamp?: string;
    thinking?: string;
    has_tools?: boolean;
    tool_calls?: Array<{ name: string; arguments: Record<string, unknown> }>;
  }>;
  isConnected: boolean;
  isStreaming: boolean;
  currentThinking: string;
  sendMessage: (content: string) => void;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  selectModel: (model: string) => void;
  reconnect: () => void;
}

export const ChatContext: Context<ChatContextValue | null> = createContext<ChatContextValue | null>(null);
