import axios, { AxiosError } from 'axios';
import type { Session, Config, Message, ApiError } from '../types';

const API_BASE = ''; // Use relative path - goes through Vite proxy in dev

const API_TIMEOUT = Math.max(1000, parseInt(import.meta.env.VITE_API_TIMEOUT || '10000', 10) || 10000);

class ApiClient {
  private client;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE,
      timeout: API_TIMEOUT,
      headers: { 'Content-Type': 'application/json' },
    });

    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError<ApiError>) => {
        const message = error.response?.data?.error || error.message || 'Unknown error';
        console.error(`API Error: ${message}`);
        return Promise.reject(new Error(message));
      }
    );
  }

  async getModels(provider?: string): Promise<string[]> {
    const params = provider ? `?provider=${encodeURIComponent(provider)}` : '';
    const res = await this.client.get<{ models: string[] }>(`/api/models${params}`);
    return res.data.models || [];
  }

  async getConfig(): Promise<Config> {
    const res = await this.client.get<{ config: Config }>('/api/config');
    return res.data.config;
  }

  async getSessions(): Promise<Session[]> {
    const res = await this.client.get<{ sessions: Session[] }>('/api/sessions');
    return res.data.sessions || [];
  }

  async createSession(): Promise<{ session_id: string }> {
    const res = await this.client.post<{ session_id: string }>('/api/sessions');
    return res.data;
  }

  async loadSession(sessionId: string): Promise<{
    session_id: string;
    title: string | null;
    messages: Message[];
  }> {
    const res = await this.client.get<{
      session_id: string;
      title: string | null;
      messages: Message[];
    }>(`/api/sessions/${sessionId}`);
    return res.data;
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.client.delete(`/api/sessions/${sessionId}`);
  }

  async renameSession(sessionId: string, newTitle: string): Promise<void> {
    await this.client.post('/api/sessions/rename', { session_id: sessionId, new_title: newTitle });
  }

  async getPreferences(): Promise<{ model?: string; provider?: string }> {
    const res = await this.client.get<{ model?: string; provider?: string }>('/api/preferences');
    return res.data;
  }

  async setPreferences(prefs: { model: string; provider?: string }): Promise<void> {
    await this.client.post('/api/preferences', prefs);
  }

  async healthCheck(): Promise<boolean> {
    try {
      const res = await this.client.get('/api/health');
      return res.status === 200;
    } catch {
      return false;
    }
  }

  async getStatus(): Promise<{ locked: boolean; needs_setup: boolean }> {
    const res = await this.client.get<{ locked: boolean; needs_setup: boolean }>('/api/status');
    return res.data;
  }

  async unlock(password: string): Promise<void> {
    await this.client.post('/api/unlock', { password });
  }

  async setup(password: string, confirm: string): Promise<void> {
    await this.client.post('/api/setup', { password, confirm });
  }

}

export const api = new ApiClient();
