import { createContext, type Context } from 'react';
import type { ToolCall } from '../types';

export type ConnectionStatus = 'connected' | 'connecting' | 'disconnected' | 'reconnecting';

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
    tool_calls?: ToolCall[];
    error?: string;
  }>;
  connectionStatus: ConnectionStatus;
  isConnected: boolean;
  isStreaming: boolean;
  currentThinking: string;
  sidebarOpen: boolean;
  setSidebarOpen: (open: boolean) => void;
  sendMessage: (content: string) => void;
  stopGeneration: () => void;
  editMessage: (index: number, newText: string) => void;
  retryMessage: (index: number) => void;
  createSession: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  selectModel: (model: string) => void;
  reconnect: () => void;
}

export const ChatContext: Context<ChatContextValue | null> = createContext<ChatContextValue | null>(
  null
);
