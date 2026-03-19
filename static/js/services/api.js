// API service module - handles REST API calls

export class ApiService {
    constructor() {
        this.baseUrl = '';
    }

    async fetchModels() {
        const response = await fetch('/api/models');
        return response.json();
    }

    async fetchSessions() {
        const response = await fetch('/api/sessions');
        return response.json();
    }

    async createSession() {
        const response = await fetch('/api/sessions', {
            method: 'POST',
        });
        return response.json();
    }

    async loadSession(sessionId) {
        const response = await fetch(`/api/sessions/${sessionId}`);
        return response.json();
    }

    async deleteSession(sessionId) {
        const response = await fetch(`/api/sessions/${sessionId}`, {
            method: 'DELETE',
        });
        return response.json();
    }

    async renameSession(sessionId, newTitle) {
        const response = await fetch('/api/sessions/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, new_title: newTitle }),
        });
        return response.json();
    }

    async purgeSessions(days = null) {
        const url = days ? `/api/sessions/purge?days=${days}` : '/api/sessions/purge';
        const response = await fetch(url, { method: 'POST' });
        return response.json();
    }

    async updateModel(provider, model, apiKey = null) {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider,
                model,
                api_key: apiKey,
            }),
        });
        return response.json();
    }

    async runWorkflow(workflowId, topic) {
        const response = await fetch('/api/workflows/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow_id: workflowId, topic }),
        });
        return response.json();
    }
}

export const api = new ApiService();
