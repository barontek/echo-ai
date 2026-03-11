// Echo AI - Vanilla JS Frontend

class EchoAI {
    constructor() {
        this.ws = null;
        this.messages = [];
        this.currentSession = null;
        this.isStreaming = false;
        this.theme = localStorage.getItem('theme') || 'dark';
        
        this.init();
    }
    
    init() {
        this.bindEvents();
        this.loadModels();
        this.loadSessions();
        this.applyTheme();
        this.connectWebSocket();
    }
    
    bindEvents() {
        // Chat form
        document.getElementById('chat-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendMessage();
        });
        
        // Theme toggle
        document.getElementById('theme-toggle').addEventListener('change', (e) => {
            this.theme = e.target.checked ? 'dark' : 'light';
            localStorage.setItem('theme', this.theme);
            this.applyTheme();
        });
        
        // New chat button
        document.getElementById('new-chat-btn').addEventListener('click', () => {
            this.newChat();
        });
        
        // Model selection
        document.getElementById('ollama-model').addEventListener('change', (e) => {
            this.updateModel(e.target.value);
        });
        
        // Stop button
        document.getElementById('stop-btn').addEventListener('click', () => {
            this.stopGeneration();
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                const input = document.getElementById('chat-input');
                if (document.activeElement === input) {
                    e.preventDefault();
                    this.sendMessage();
                }
            }
        });
    }
    
    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        this.ws = new WebSocket(`${protocol}//${window.location.host}/ws/chat`);
        
        this.ws.onopen = () => {
            console.log('WebSocket connected');
            // Send initial config
            const model = document.getElementById('ollama-model').value;
            this.ws.send(JSON.stringify({
                provider: 'ollama',
                model: model
            }));
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected, reconnecting...');
            setTimeout(() => this.connectWebSocket(), 3000);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'ready':
                console.log('Agent ready');
                break;
                
            case 'message':
                // Skip user messages - we already added them locally
                if (data.role !== 'user') {
                    this.addMessage(data.role, data.content, data.timestamp);
                }
                break;
                
            case 'thinking':
                this.updateThinking(data.content);
                break;
                
            case 'content':
                this.updateContent(data.content);
                break;
                
            case 'done':
                this.finishMessage(data.content, data.thinking, data.timestamp);
                break;
                
            case 'stopped':
                this.resetButtons();
                break;
                
            case 'error':
                this.showError(data.content);
                this.resetButtons();
                break;
        }
    }
    
    async loadModels() {
        try {
            const response = await fetch('/api/models');
            const data = await response.json();
            const select = document.getElementById('ollama-model');
            select.innerHTML = '';
            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = model;
                option.textContent = model;
                if (model === 'qwen3:4b-instruct') {
                    option.selected = true;
                }
                select.appendChild(option);
            });
        } catch (e) {
            console.error('Failed to load models:', e);
        }
    }
    
    async loadSessions() {
        try {
            const response = await fetch('/api/sessions');
            const data = await response.json();
            this.renderSessions(data.sessions);
        } catch (e) {
            console.error('Failed to load sessions:', e);
        }
    }
    
    renderSessions(sessions) {
        const container = document.getElementById('session-list');
        container.innerHTML = '';
        
        if (sessions.length === 0) {
            container.innerHTML = '<div class="session-item">No sessions yet</div>';
            return;
        }
        
        sessions.forEach(session => {
            const div = document.createElement('div');
            div.className = 'session-item' + (session === this.currentSession ? ' active' : '');
            div.textContent = session;
            div.addEventListener('click', () => this.loadSession(session));
            container.appendChild(div);
        });
    }
    
    async newChat() {
        try {
            await fetch('/api/sessions', { method: 'POST' });
            this.currentSession = null;
            this.messages = [];
            this.renderMessages();
            this.loadSessions();
        } catch (e) {
            console.error('Failed to create session:', e);
        }
    }
    
    async loadSession(sessionId) {
        try {
            const response = await fetch(`/api/sessions/${sessionId}`);
            const data = await response.json();
            this.currentSession = sessionId;
            this.messages = data.messages || [];
            this.renderMessages();
            this.renderSessions((await fetch('/api/sessions').then(r => r.json())).sessions);
        } catch (e) {
            console.error('Failed to load session:', e);
        }
    }
    
    async updateModel(model) {
        try {
            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider: 'ollama',
                    model: model
                })
            });
            document.getElementById('model-badge').textContent = `Model: ${model}`;
        } catch (e) {
            console.error('Failed to update model:', e);
        }
    }
    
    sendMessage() {
        if (this.isStreaming) return;
        
        const input = document.getElementById('chat-input');
        const content = input.value.trim();
        
        if (!content) return;
        
        input.value = '';
        this.isStreaming = true;
        
        // Toggle buttons
        document.getElementById('send-btn').style.display = 'none';
        document.getElementById('stop-btn').style.display = 'block';
        
        // Add user message immediately for UI feedback
        const timestamp = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
        this.addMessage('user', content, timestamp);
        
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ content }));
        }
    }
    
    stopGeneration() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ type: "stop" }));
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
        this.renderMessage(message, this.messages.length - 1);
        this.scrollToBottom();
    }
    
    // Helper to ensure we have a bot message when receiving bot responses
    ensureBotMessage() {
        const lastMessage = this.messages[this.messages.length - 1];
        if (lastMessage && lastMessage.role === 'user') {
            // Create a new bot message
            this.addMessage('assistant', '', '');
        }
    }
    
    updateThinking(thinking) {
        if (this.messages.length === 0) return;
        
        // If last message is from user, create a new bot message first
        this.ensureBotMessage();
        
        const lastMessage = this.messages[this.messages.length - 1];
        
        if (!lastMessage.thinking) {
            lastMessage.thinking = '';
            // Create thinking expander if it doesn't exist
            const msgEl = document.querySelector('.message:last-child');
            let thinkingContainer = msgEl.querySelector('.thinking-container');
            if (!thinkingContainer) {
                const contentEl = msgEl.querySelector('.message-content');
                thinkingContainer = document.createElement('div');
                thinkingContainer.className = 'thinking-container';
                thinkingContainer.innerHTML = `
                    <div class="thinking-header" onclick="this.nextElementSibling.classList.toggle('collapsed'); this.querySelector('span').textContent = this.nextElementSibling.classList.contains('collapsed') ? '▶' : '▼'">
                        <span>▶</span> Thought Process
                    </div>
                    <div class="thinking-content"></div>
                `;
                // Insert before content
                msgEl.insertBefore(thinkingContainer, contentEl);
            }
        }
        lastMessage.thinking = thinking;
        
        const thinkingEl = document.querySelector('.message:last-child .thinking-content');
        if (thinkingEl) {
            thinkingEl.textContent = thinking;
        }
        
        this.scrollToBottom();
    }
    
    updateContent(content) {
        if (this.messages.length === 0) return;
        
        // If last message is from user, create a new bot message first
        this.ensureBotMessage();
        
        const lastMessage = this.messages[this.messages.length - 1];
        lastMessage.content = content;
        
        const contentEl = document.querySelector('.message:last-child .message-content');
        if (contentEl) {
            contentEl.innerHTML = this.formatContent(content);
        }
        
        this.scrollToBottom();
    }
    
    finishMessage(content, thinking, timestamp) {
        this.resetButtons();
        
        if (this.messages.length === 0) return;
        
        const lastMessage = this.messages[this.messages.length - 1];
        lastMessage.content = content;
        lastMessage.thinking = thinking;
        lastMessage.timestamp = timestamp;
        
        // Re-render the last message
        const msgEl = document.querySelector('.message:last-child');
        if (msgEl) {
            msgEl.classList.remove('streaming');
            msgEl.querySelector('.message-content').innerHTML = this.formatContent(content);
            
            // Add thinking expander only if it doesn't already exist
            if (thinking && !msgEl.querySelector('.thinking-container')) {
                const metaEl = msgEl.querySelector('.message-meta');
                const thinkingContainer = document.createElement('div');
                thinkingContainer.className = 'thinking-container';
                thinkingContainer.innerHTML = `
                    <div class="thinking-header" onclick="this.nextElementSibling.classList.toggle('collapsed'); this.querySelector('span').textContent = this.nextElementSibling.classList.contains('collapsed') ? '▶' : '▼'">
                        <span>▶</span> Thought Process
                    </div>
                    <div class="thinking-content collapsed">${this.escapeHtml(thinking)}</div>
                `;
                metaEl.parentNode.insertBefore(thinkingContainer, metaEl);
            }
            
            // Add timestamp
            if (timestamp) {
                const metaEl = msgEl.querySelector('.message-meta');
                if (!metaEl.querySelector('.message-time')) {
                    const timeEl = document.createElement('span');
                    timeEl.className = 'message-time';
                    timeEl.textContent = timestamp;
                    metaEl.appendChild(timeEl);
                }
            }
        }
    }
    
    renderMessages() {
        const container = document.getElementById('chat-container');
        container.innerHTML = '';
        
        if (this.messages.length === 0) {
            this.renderEmptyState();
            return;
        }
        
        this.messages.forEach((msg, i) => this.renderMessage(msg, i));
    }
    
    renderMessage(message, index) {
        const container = document.getElementById('chat-container');
        
        // Clear empty state if present
        const emptyState = container.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }
        
        const div = document.createElement('div');
        div.className = `message message-${message.role === 'user' ? 'user' : 'bot'}`;
        
        // For bot messages, add thinking BEFORE content
        if (message.role === 'assistant' && message.thinking) {
            const thinkingContainer = document.createElement('div');
            thinkingContainer.className = 'thinking-container';
            thinkingContainer.innerHTML = `
                <div class="thinking-header" onclick="this.nextElementSibling.classList.toggle('collapsed'); this.querySelector('span').textContent = this.nextElementSibling.classList.contains('collapsed') ? '▶' : '▼'">
                    <span>▶</span> Thought Process
                </div>
                <div class="thinking-content collapsed">${this.escapeHtml(message.thinking)}</div>
            `;
            div.appendChild(thinkingContainer);
        }
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = this.formatContent(message.content);
        
        div.appendChild(contentDiv);
        
        // Add meta (timestamp for bot)
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
        this.scrollToBottom();
    }
    
    renderEmptyState() {
        const container = document.getElementById('chat-container');
        container.innerHTML = `
            <div class="empty-state">
                <h2>How can I help you today?</h2>
                <div class="quick-actions">
                    <button class="btn" onclick="app.quickAction('Search the web for the latest news on Artificial Intelligence')">Search AI News</button>
                    <button class="btn" onclick="app.quickAction('Write a python script that implements a simple FastAPI server')">Write Python Server</button>
                    <button class="btn" onclick="app.quickAction('Help me extract structured entity data from a messy block of text')">Extract Data</button>
                </div>
            </div>
        `;
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
        this.scrollToBottom();
    }
    
    scrollToBottom() {
        const container = document.getElementById('chat-container');
        container.scrollTop = container.scrollHeight;
    }
    
    formatContent(content) {
        // Basic markdown-like formatting
        let formatted = this.escapeHtml(content);
        
        // Code blocks
        formatted = formatted.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        
        // Inline code
        formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');
        
        // Bold
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        
        // Italic
        formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        
        // Links
        formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
        
        return formatted;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    applyTheme() {
        document.documentElement.setAttribute('data-theme', this.theme);
        document.getElementById('theme-toggle').checked = this.theme === 'dark';
    }
}

// Initialize app
const app = new EchoAI();
