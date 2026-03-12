// Echo AI - Vanilla JS Frontend

class EchoAI {
    constructor() {
        this.ws = null;
        this.messages = [];
        this.currentSession = null;
        this.isStreaming = false;
        this.theme = localStorage.getItem('theme') || 'dark';
        this.reconnectTimer = null;
        this.pendingContent = null;
        this.pendingThinking = null;
        this.renderScheduled = false;
        this.streamMetrics = { startMs: 0, firstTokenMs: 0 };
        this.init();
    }

    init() {
        this.bindEvents();
        this.setLoadingModels();
        this.loadModels();
        this.loadSessions();
        this.applyTheme();
        this.connectWebSocket();
        this.updateMetrics();
    }

    bindEvents() {
        document.getElementById('chat-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendMessage();
        });

        document.getElementById('theme-toggle').addEventListener('change', (e) => {
            this.theme = e.target.checked ? 'dark' : 'light';
            localStorage.setItem('theme', this.theme);
            this.applyTheme();
        });

        document.getElementById('new-chat-btn').addEventListener('click', () => this.newChat());
        document.getElementById('delete-session-btn').addEventListener('click', () => this.deleteCurrentSession());
        document.getElementById('rename-session-btn').addEventListener('click', () => this.renameCurrentSession());

        document.getElementById('ollama-model').addEventListener('change', (e) => {
            this.updateModel(e.target.value);
        });

        document.getElementById('stop-btn').addEventListener('click', () => this.stopGeneration());

        document.getElementById('session-search').addEventListener('input', () => this.loadSessions());

        document.getElementById('open-workflows-btn').addEventListener('click', () => this.openWorkflowsWindow());

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                const input = document.getElementById('chat-input');
                if (document.activeElement === input) {
                    e.preventDefault();
                    this.sendMessage();
                }
            }
        });

        document.getElementById('chat-container').addEventListener('click', (e) => {
            const header = e.target.closest('.thinking-header');
            if (!header) return;
            const content = header.nextElementSibling;
            content.classList.toggle('collapsed');
            const icon = header.querySelector('.thinking-icon');
            icon.textContent = content.classList.contains('collapsed') ? '▶' : '▼';
        });
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);

        this.ws.onopen = () => {
            this.showConnectionBanner('Connected', false);
            this.clearReconnect();
            const model = document.getElementById('ollama-model').value;
            this.ws.send(JSON.stringify({ provider: 'ollama', model }));
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'ping') {
                this.ws.send(JSON.stringify({ type: 'pong' }));
                return;
            }
            this.handleWebSocketMessage(data);
        };

        this.ws.onclose = () => this.startReconnect();
        this.ws.onerror = () => this.startReconnect();
    }

    startReconnect() {
        if (this.reconnectTimer) return;
        let remaining = 3;
        this.showConnectionBanner(`Disconnected. Reconnecting in ${remaining}s...`, true);
        this.reconnectTimer = setInterval(() => {
            remaining -= 1;
            if (remaining <= 0) {
                this.clearReconnect();
                this.connectWebSocket();
                return;
            }
            this.showConnectionBanner(`Disconnected. Reconnecting in ${remaining}s...`, true);
        }, 1000);
    }

    clearReconnect() {
        if (this.reconnectTimer) {
            clearInterval(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }

    showConnectionBanner(message, visible) {
        const banner = document.getElementById('connection-banner');
        banner.textContent = message;
        banner.style.display = visible ? 'block' : 'none';
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'message':
                if (data.role !== 'user') {
                    this.addMessage(data.role, data.content, data.timestamp);
                }
                break;
            case 'thinking':
                this.pendingThinking = data.content;
                this.scheduleRender();
                break;
            case 'content':
                if (!this.streamMetrics.firstTokenMs) {
                    this.streamMetrics.firstTokenMs = performance.now();
                }
                this.pendingContent = data.content;
                this.scheduleRender();
                break;
            case 'done':
                this.flushPendingRender();
                this.finishMessage(data.content, data.thinking, data.timestamp);
                break;
            case 'error':
                this.showError(data.content);
                this.resetButtons();
                break;
            default:
                break;
        }
    }

    scheduleRender() {
        if (this.renderScheduled) return;
        this.renderScheduled = true;
        window.requestAnimationFrame(() => {
            this.renderScheduled = false;
            this.flushPendingRender();
        });
    }

    flushPendingRender() {
        if (this.pendingThinking !== null) {
            this.updateThinking(this.pendingThinking);
            this.pendingThinking = null;
        }
        if (this.pendingContent !== null) {
            this.updateContent(this.pendingContent);
            this.pendingContent = null;
        }
    }

    setLoadingModels() {
        const select = document.getElementById('ollama-model');
        select.innerHTML = '<option>Loading models...</option>';
    }

    async loadModels() {
        try {
            const response = await fetch('/api/models');
            const data = await response.json();
            const select = document.getElementById('ollama-model');
            select.innerHTML = '';
            data.models.forEach((model) => {
                const option = document.createElement('option');
                option.value = model;
                option.textContent = model;
                if (model === 'qwen3:4b-instruct') option.selected = true;
                select.appendChild(option);
            });
        } catch {
            this.setLoadingModels();
        }
    }

    async loadSessions() {
        try {
            const response = await fetch('/api/sessions');
            const data = await response.json();
            this.renderSessions(data.sessions);
        } catch {
            this.renderSessions([]);
        }
    }

    renderSessions(sessions) {
        const filter = document.getElementById('session-search').value.trim().toLowerCase();
        const visibleSessions = sessions.filter((s) => s.toLowerCase().includes(filter));

        const container = document.getElementById('session-list');
        container.innerHTML = '';
        if (visibleSessions.length === 0) {
            container.innerHTML = '<div class="session-item">No sessions</div>';
            return;
        }

        visibleSessions.forEach((session) => {
            const div = document.createElement('button');
            div.className = 'session-item' + (session === this.currentSession ? ' active' : '');
            div.textContent = session;
            div.type = 'button';
            div.addEventListener('click', () => this.loadSession(session));
            container.appendChild(div);
        });
    }

    async newChat() {
        await fetch('/api/sessions', { method: 'POST' });
        this.currentSession = null;
        this.messages = [];
        this.renderMessages();
        this.loadSessions();
    }



    openWorkflowsWindow() {
        window.open('/workflows', '_blank', 'noopener,noreferrer');
    }

    async loadSession(sessionId) {
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();
        this.currentSession = sessionId;
        this.messages = data.messages || [];
        this.renderMessages();
        this.loadSessions();
    }

    async deleteCurrentSession() {
        if (!this.currentSession) return;
        await fetch(`/api/sessions/${this.currentSession}`, { method: 'DELETE' });
        this.currentSession = null;
        this.messages = [];
        this.renderMessages();
        this.loadSessions();
    }

    async renameCurrentSession() {
        if (!this.currentSession) return;
        const nextName = window.prompt('Rename session to:', this.currentSession);
        if (!nextName || nextName === this.currentSession) return;

        const response = await fetch('/api/sessions/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.currentSession, new_session_id: nextName }),
        });

        if (!response.ok) return;
        this.currentSession = nextName;
        this.loadSessions();
    }

    async updateModel(model) {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: 'ollama', model }),
        });
        document.getElementById('model-badge').textContent = `Model: ${model}`;
    }

    sendMessage() {
        if (this.isStreaming) return;
        const input = document.getElementById('chat-input');
        const content = input.value.trim();
        if (!content) return;

        input.value = '';
        this.isStreaming = true;
        this.streamMetrics = { startMs: performance.now(), firstTokenMs: 0 };
        document.getElementById('send-btn').style.display = 'none';
        document.getElementById('stop-btn').style.display = 'block';

        const timestamp = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
        this.addMessage('user', content, timestamp);

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ content }));
        }
    }

    stopGeneration() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: 'stop' }));
        }
    }

    resetButtons() {
        this.isStreaming = false;
        document.getElementById('send-btn').style.display = 'block';
        document.getElementById('stop-btn').style.display = 'none';
    }

    addMessage(role, content, timestamp = '') {
        const message = { role, content, timestamp };
        this.messages.push(message);
        this.renderMessage(message);
        this.smartScroll();
        this.updateMetrics();
    }

    ensureBotMessage() {
        const lastMessage = this.messages[this.messages.length - 1];
        if (lastMessage && lastMessage.role === 'user') {
            this.addMessage('assistant', '', '');
            const lastEl = document.querySelector('.message:last-child');
            if (lastEl) lastEl.classList.add('streaming');
        }
    }

    updateThinking(thinking) {
        if (this.messages.length === 0) return;
        this.ensureBotMessage();

        const lastMessage = this.messages[this.messages.length - 1];
        lastMessage.thinking = thinking;

        const msgEl = document.querySelector('.message:last-child');
        if (!msgEl) return;

        let thinkingContainer = msgEl.querySelector('.thinking-container');
        if (!thinkingContainer) {
            thinkingContainer = this.createThinkingContainer('');
            msgEl.insertBefore(thinkingContainer, msgEl.querySelector('.message-content'));
        }

        const thinkingEl = thinkingContainer.querySelector('.thinking-content');
        thinkingEl.textContent = thinking;
        this.smartScroll();
    }

    updateContent(content) {
        if (this.messages.length === 0) return;
        this.ensureBotMessage();

        const lastMessage = this.messages[this.messages.length - 1];
        lastMessage.content = content;

        const contentEl = document.querySelector('.message:last-child .message-content');
        if (contentEl) {
            contentEl.innerHTML = this.formatContent(content);
        }
        this.smartScroll();
    }

    finishMessage(content, thinking, timestamp) {
        this.resetButtons();
        if (this.messages.length === 0) return;

        const lastMessage = this.messages[this.messages.length - 1];
        lastMessage.content = content;
        lastMessage.thinking = thinking;
        lastMessage.timestamp = timestamp;

        const msgEl = document.querySelector('.message:last-child');
        if (!msgEl) return;

        msgEl.classList.remove('streaming');
        msgEl.querySelector('.message-content').innerHTML = this.formatContent(content);

        if (thinking && !msgEl.querySelector('.thinking-container')) {
            const thinkingContainer = this.createThinkingContainer(thinking, true);
            msgEl.insertBefore(thinkingContainer, msgEl.querySelector('.message-meta'));
        }

        const metaEl = msgEl.querySelector('.message-meta');
        if (timestamp && metaEl && !metaEl.querySelector('.message-time')) {
            const timeEl = document.createElement('span');
            timeEl.className = 'message-time';
            timeEl.textContent = timestamp;
            metaEl.appendChild(timeEl);
        }

        const total = Math.round(performance.now() - this.streamMetrics.startMs);
        const ttfb = this.streamMetrics.firstTokenMs
            ? Math.round(this.streamMetrics.firstTokenMs - this.streamMetrics.startMs)
            : total;
        this.updateMetrics({ ttfb, total });
    }

    createThinkingContainer(thinking, collapsed = false) {
        const container = document.createElement('div');
        container.className = 'thinking-container';
        container.innerHTML = `
            <button type="button" class="thinking-header" aria-label="Toggle thought process">
                <span class="thinking-icon">${collapsed ? '▶' : '▼'}</span> Thought Process
            </button>
            <div class="thinking-content ${collapsed ? 'collapsed' : ''}"></div>
        `;
        container.querySelector('.thinking-content').textContent = thinking;
        return container;
    }

    renderMessages() {
        const container = document.getElementById('chat-container');
        container.innerHTML = '';

        if (this.messages.length === 0) {
            this.renderEmptyState();
            this.updateMetrics();
            return;
        }

        const windowSize = 120;
        const start = Math.max(0, this.messages.length - windowSize);
        this.messages.slice(start).forEach((msg) => this.renderMessage(msg));
        this.smartScroll(true);
        this.updateMetrics();
    }

    renderMessage(message) {
        const container = document.getElementById('chat-container');
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) emptyState.remove();

        const div = document.createElement('div');
        div.className = `message message-${message.role === 'user' ? 'user' : 'bot'}`;

        if (message.role === 'assistant' && message.thinking) {
            div.appendChild(this.createThinkingContainer(message.thinking, true));
        }

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = this.formatContent(message.content || '');
        div.appendChild(contentDiv);

        if (message.role === 'assistant') {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'message-meta';
            if (message.timestamp) {
                const timeEl = document.createElement('span');
                timeEl.className = 'message-time';
                timeEl.textContent = message.timestamp;
                metaDiv.appendChild(timeEl);
            }
            div.appendChild(metaDiv);
        }

        container.appendChild(div);
    }

    renderEmptyState() {
        const container = document.getElementById('chat-container');
        container.innerHTML = `
            <div class="empty-state">
                <h2>How can I help you today?</h2>
                <div class="quick-actions">
                    <button class="btn" type="button" data-prompt="Search the web for the latest news on Artificial Intelligence">Search AI News</button>
                    <button class="btn" type="button" data-prompt="Write a python script that implements a simple FastAPI server">Write Python Server</button>
                    <button class="btn" type="button" data-prompt="Help me extract structured entity data from a messy block of text">Extract Data</button>
                </div>
            </div>
        `;

        container.querySelectorAll('[data-prompt]').forEach((btn) => {
            btn.addEventListener('click', () => this.quickAction(btn.dataset.prompt));
        });
    }

    quickAction(prompt) {
        document.getElementById('chat-input').value = prompt;
        this.sendMessage();
    }

    showError(message) {
        this.isStreaming = false;
        const container = document.getElementById('chat-container');
        const div = document.createElement('div');
        div.className = 'message message-bot';
        div.style.backgroundColor = '#ff4444';
        div.innerHTML = `<div class="message-content">Error: ${this.escapeHtml(message)}</div>`;
        container.appendChild(div);
        this.smartScroll(true);
    }

    smartScroll(force = false) {
        const container = document.getElementById('chat-container');
        const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
        if (force || distance < 120) {
            container.scrollTop = container.scrollHeight;
        }
    }

    formatContent(content) {
        let formatted = this.escapeHtml(content);
        formatted = formatted.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
        return formatted;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    updateMetrics(extra = null) {
        const msgCount = this.messages.length;
        const badge = document.getElementById('metrics-badge');
        if (!extra) {
            badge.textContent = `Messages: ${msgCount}`;
            return;
        }
        badge.textContent = `Messages: ${msgCount} · TTFB: ${extra.ttfb}ms · Total: ${extra.total}ms`;
    }

    applyTheme() {
        document.documentElement.setAttribute('data-theme', this.theme);
        document.getElementById('theme-toggle').checked = this.theme === 'dark';
    }
}

const app = new EchoAI();
