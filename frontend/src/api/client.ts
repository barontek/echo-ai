import axios, { AxiosError } from 'axios';
import type { Session, Config, Message, ApiError } from '../types';

const API_BASE = ''; // Use relative path - goes through Vite proxy in dev

class ApiClient {
  private client;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE,
      timeout: 10000,
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

  async getModels(): Promise<string[]> {
    const res = await this.client.get<{ models: string[] }>('/api/models');
    return res.data.models || [];
  }

  async getConfig(): Promise<Config> {
    const res = await this.client.get<{ config: Config }>('/api/config');
    return res.data.config;
  }

  async updateConfig(provider: string, model: string, apiKey?: string): Promise<void> {
    await this.client.post('/api/config', { provider, model, api_key: apiKey });
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

  async healthCheck(): Promise<{ status: string; version: string }> {
    const res = await this.client.get<{ status: string; version: string }>('/health');
    return res.data;
  }
}

export const api = new ApiClient();
