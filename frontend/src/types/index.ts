// Centralized types for the application

export interface Session {
  id: string;
  title: string;
  created_at: string;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  thinking?: string;
  has_tools?: boolean;
  tool_calls?: ToolCall[];
}

export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
}

export interface Config {
  provider: string;
  model: string;
  temperature: number;
  max_iterations: number;
  session_enabled: boolean;
}

export interface StreamEvent {
  type: 'ready' | 'message' | 'content' | 'thinking' | 'done' | 'error' | 'pong' | 'session_start';
  content?: string;
  thinking?: string;
  has_tools?: boolean;
  tool_calls?: ToolCall[];
  session_id?: string;
  title?: string;
  timestamp?: string;
  role?: string;
}

export interface ApiError {
  error: string;
  detail?: string;
}
