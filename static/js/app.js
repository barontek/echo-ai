// Echo AI - Vanilla JS Frontend

class EchoAI {
    constructor() {
        this.ws = null;
        this.messages = [];
        this.currentSession = localStorage.getItem('currentSession');
        this.isStreaming = false;
        this.theme = localStorage.getItem('theme') || 'dark';
        this.reconnectTimer = null;
        this.pendingContent = null;
        this.pendingThinking = null;
        this.pendingUserMessage = null; // Buffered message for connection startup
        this.renderScheduled = false;
        this.streamMetrics = { startMs: 0, firstTokenMs: 0 };
        this.isMobileView = window.matchMedia('(max-width: 900px)');
        this.init();
    }

    async init() {
        this.bindEvents();
        this.setLoadingModels();
        const hasModels = await this.loadModels();
        this.loadSessions();
        this.applyTheme();
        if (this.currentSession) {
            this.loadSession(this.currentSession);
        }
        if (hasModels) {
            this.connectWebSocket();
        } else {
            this.showError('No models found. Please check if Ollama is running.');
        }
        this.updateMetrics();
        this.syncSidebarWithViewport();
    }

    createSourcesContainer(content) {
        const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g;
        const links = [];
        let match;
        while ((match = linkRegex.exec(content)) !== null) {
            // Deduplicate URLs
            if (!links.some(l => l.url === match[2])) {
                links.push({ text: match[1], url: match[2] });
            }
        }

        if (links.length === 0) return null;

        const container = document.createElement('div');
        container.className = 'sources-container';
        container.innerHTML = `
            <button type="button" class="sources-header" aria-label="Toggle sources">
                <span class="sources-icon">▶</span> Sources (${links.length})
            </button>
            <div class="sources-content collapsed">
                ${links.map(link => `<a href="${link.url}" target="_blank" rel="noopener noreferrer">🔗 ${link.text}</a>`).join('')}
            </div>
        `;

        // Add toggle listener
        const header = container.querySelector('.sources-header');
        const contentDiv = container.querySelector('.sources-content');
        const icon = container.querySelector('.sources-icon');
        header.addEventListener('click', () => {
            contentDiv.classList.toggle('collapsed');
            icon.textContent = contentDiv.classList.contains('collapsed') ? '▼' : '▶';
        });

        return container;
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
        document.getElementById('purge-sessions-btn').addEventListener('click', () => this.purgeSessions());

        document.getElementById('ollama-model').addEventListener('change', (e) => {
            this.updateModel(e.target.value);
        });

        document.getElementById('stop-btn').addEventListener('click', () => this.stopGeneration());

        document.getElementById('session-search').addEventListener('input', () => this.loadSessions());

        document.getElementById('open-workflows-btn').addEventListener('click', () => this.openWorkflowsWindow());

        document.getElementById('sidebar-toggle').addEventListener('click', () => this.toggleSidebar());

        this.isMobileView.addEventListener('change', () => this.syncSidebarWithViewport());

        document.querySelector('.main').addEventListener('click', () => {
            if (this.isMobileView.matches && document.querySelector('.app').classList.contains('sidebar-open')) {
                this.toggleSidebar(false);
            }
        });

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
            const modelSelect = document.getElementById('ollama-model');
            const model = modelSelect.value;
            if (model && model !== 'Loading models...') {
                const payload = { provider: 'ollama', model };
                if (this.currentSession) {
                    payload.session_id = this.currentSession;
                }
                this.ws.send(JSON.stringify(payload));
            }
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

    reconnectWithNewSession() {
        if (this.ws) {
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.onmessage = null; // Destroy the old listener to prevent ghost messages
            this.ws.close();
        }
        this.connectWebSocket();
    }

    showConnectionBanner(message, visible) {
        const banner = document.getElementById('connection-banner');
        banner.textContent = message;
        banner.style.display = visible ? 'block' : 'none';
    }

    handleWebSocketMessage(data) {
        if (data.session_id && data.session_id !== this.currentSession) {
            this.currentSession = data.session_id;
            localStorage.setItem('currentSession', this.currentSession);
            this.loadSessions();
        }

        if (data.title && data.session_id === this.currentSession) {
             // Successfully captured an auto-generated or updated title
             this.loadSessions();
        }

        switch (data.type) {
            case 'ready':
                // Send the buffered message the millisecond the backend confirms the new session
                if (this.pendingUserMessage) {
                    this.ws.send(JSON.stringify({ content: this.pendingUserMessage }));
                    this.pendingUserMessage = null;
                }
                break;
            case 'message':
                if (data.role !== 'user') {
                    this.addMessage(data.role, data.content, data.timestamp);
                }
                break;
            case 'thinking':
                this.updateThinking(data.content);
                break;
            case 'title':
                if (data.title) {
                    this.updateSessionTitle(data.session_id, data.title);
                }
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
                this.finishMessage(data.content, data.thinking, data.timestamp, data.has_tools);
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
            if (!data.models || data.models.length === 0) return false;

            select.innerHTML = '';
            data.models.forEach((model) => {
                const option = document.createElement('option');
                option.value = model;
                option.textContent = model;
                if (model === 'qwen3:4b-instruct') option.selected = true;
                select.appendChild(option);
            });
            return true;
        } catch {
            this.setLoadingModels();
            return false;
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
        const visibleSessions = sessions.filter((s) => {
            const titleMatch = s.title && s.title.toLowerCase().includes(filter);
            const idMatch = s.id && s.id.toLowerCase().includes(filter);
            return titleMatch || idMatch;
        });

        const container = document.getElementById('session-list');
        container.innerHTML = '';
        if (visibleSessions.length === 0) {
            container.innerHTML = '<div class="session-item">No sessions</div>';
            return;
        }

        visibleSessions.forEach((session) => {
            const div = document.createElement('button');
            div.className = 'session-item' + (session.id === this.currentSession ? ' active' : '');
            div.textContent = session.title || session.id;
            div.title = session.id; // Tooltip shows raw ID
            div.type = 'button';
            div.addEventListener('click', () => this.loadSession(session.id));
            container.appendChild(div);
        });
    }

    async newChat() {
        // Drop the fetch to /api/sessions entirely!
        // Setting this to null forces the new WebSocket to create its own flawless session.
        this.currentSession = null;
        localStorage.removeItem('currentSession');
        this.messages = [];
        this.renderMessages();
        this.loadSessions();
        this.closeSidebarOnMobile();
        this.reconnectWithNewSession();
    }



    openWorkflowsWindow() {
        window.open('/workflows', '_blank', 'noopener,noreferrer');
    }

    syncSidebarWithViewport() {
        const app = document.querySelector('.app');
        if (!this.isMobileView.matches) {
            app.classList.remove('sidebar-open');
        }
        this.updateSidebarToggleAria();
    }

    toggleSidebar(forceOpen) {
        const app = document.querySelector('.app');
        if (typeof forceOpen === 'boolean') {
            app.classList.toggle('sidebar-open', forceOpen);
        } else {
            app.classList.toggle('sidebar-open');
        }
        this.updateSidebarToggleAria();
    }

    closeSidebarOnMobile() {
        if (!this.isMobileView.matches) return;
        this.toggleSidebar(false);
    }

    updateSidebarToggleAria() {
        const toggle = document.getElementById('sidebar-toggle');
        const isOpen = document.querySelector('.app').classList.contains('sidebar-open');
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }

    async loadSession(sessionId) {
        const response = await fetch(`/api/sessions/${sessionId}`);
        const data = await response.json();
        this.currentSession = sessionId;
        localStorage.setItem('currentSession', this.currentSession);
        this.messages = data.messages || [];
        this.renderMessages();
        this.loadSessions();
        this.closeSidebarOnMobile();
        this.reconnectWithNewSession();
    }

    async deleteCurrentSession() {
        if (!this.currentSession) return;
        await fetch(`/api/sessions/${this.currentSession}`, { method: 'DELETE' });
        const deletedId = this.currentSession;
        this.currentSession = null;
        localStorage.removeItem('currentSession');
        this.messages = [];
        this.renderMessages();
        this.loadSessions();
        this.closeSidebarOnMobile();
    }

    async renameCurrentSession() {
        if (!this.currentSession) return;
        const currentItem = document.querySelector('.session-item.active');
        const currentTitle = currentItem ? currentItem.textContent : this.currentSession;
        const nextTitle = window.prompt('Rename session to:', currentTitle);
        if (!nextTitle || nextTitle === currentTitle) return;

        const response = await fetch('/api/sessions/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: this.currentSession, new_title: nextTitle }),
        });

        if (!response.ok) return;
        this.loadSessions();
    }

    async updateSessionTitle(sessionId, newTitle) {
        // Find the session in the sidebar and update its title
        const sessionItems = document.querySelectorAll('.session-item');
        sessionItems.forEach(item => {
            if (item.title === sessionId) {
                item.textContent = newTitle;
            }
        });
    }

    async purgeSessions() {
        if (!window.confirm('Are you sure you want to purge ALL session history? This cannot be undone.')) {
            return;
        }

        const response = await fetch('/api/sessions/purge', { method: 'POST' });
        if (response.ok) {
            const data = await response.json();
            this.currentSession = null;
            localStorage.removeItem('currentSession');
            this.messages = [];
            this.renderMessages();
            this.loadSessions();
            alert(`Successfully purged ${data.purged_count} sessions.`);
        } else {
            this.showError('Failed to purge sessions.');
        }
    }

    async updateModel(model) {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: 'ollama', model }),
        });
        document.getElementById('model-badge').textContent = `Model: ${model}`;
        if (this.isStreaming) return;
        this.reconnectWithNewSession();
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
        } else {
            // Store the message safely while the new socket connects
            this.pendingUserMessage = content;
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
        document.querySelectorAll('.message.streaming').forEach(m => m.classList.remove('streaming'));
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
        if (!lastMessage || lastMessage.role === 'user') {
            this.addMessage('assistant', '', '');
            const msgEl = document.querySelector('.message:last-child');
            if (msgEl) msgEl.classList.add('streaming');
        }
        return document.querySelector('.message:last-child');
    }

    // 1. NEW HELPER: Parses thoughts dynamically on the frontend
    extractThinkingLocally(content) {
        let displayContent = content || '';
        let thinking = '';

        const thinkMatch = displayContent.match(/<think>([\s\S]*?)(?:<\/think>|$)/);
        if (thinkMatch) {
            thinking = thinkMatch[1].trim();
            displayContent = displayContent.replace(/<think>[\s\S]*?(?:<\/think>|$)/, '').trim();
        } else if (displayContent.includes('__THINKING__')) {
            const parts = displayContent.split('__THINKING_END__');
            thinking = parts[0].replace('__THINKING__', '').trim();
            displayContent = parts.length > 1 ? parts[1].trim() : '';
        }

        return { displayContent, thinking };
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

        thinkingContainer.querySelector('.thinking-content').textContent = thinking;
        this.smartScroll();
    }

    // 2. UPDATED: Safely handles streaming chunks with <think> tags
    updateContent(rawContent) {
        if (this.messages.length === 0 || !this.isStreaming) return;
        this.ensureBotMessage(); // Always run first

        const { displayContent, thinking } = this.extractThinkingLocally(rawContent);
        const lastMessage = this.messages[this.messages.length - 1];

        lastMessage.content = displayContent;

        if (thinking) {
            lastMessage.thinking = thinking;
            const msgEl = document.querySelector('.message:last-child');
            if (msgEl) {
                let thinkingContainer = msgEl.querySelector('.thinking-container');
                if (!thinkingContainer) {
                    thinkingContainer = this.createThinkingContainer('');
                    msgEl.insertBefore(thinkingContainer, msgEl.querySelector('.message-content'));
                }
                thinkingContainer.querySelector('.thinking-content').textContent = thinking;
            }
        }

        const contentEl = document.querySelector('.message:last-child .message-content');
        if (contentEl) {
            contentEl.innerHTML = this.formatContent(displayContent);
        }
        this.smartScroll();
    }

    // 3. UPDATED: Safely handles non-streaming models and finalizations
    finishMessage(rawContent, backendThinking, timestamp, hasTools) {
        this.resetButtons();
        if (this.messages.length === 0) return;

        // --- THE CRITICAL FIX: Stops the user message from being overwritten ---
        this.ensureBotMessage();

        const { displayContent, thinking: extractedThinking } = this.extractThinkingLocally(rawContent);
        const finalThinking = backendThinking || extractedThinking;

        const lastMessage = this.messages[this.messages.length - 1];
        lastMessage.content = displayContent;
        lastMessage.thinking = finalThinking;
        lastMessage.timestamp = timestamp || lastMessage.timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

        const msgEl = this.ensureBotMessage();
        if (!msgEl) return;
        msgEl.classList.remove('streaming');

        if (finalThinking) {
            this.updateThinking(finalThinking);
        }

        msgEl.classList.remove('streaming');
        const contentEl = msgEl.querySelector('.message-content');
        if (contentEl) contentEl.innerHTML = this.formatContent(displayContent);

        if (finalThinking && !msgEl.querySelector('.thinking-container')) {
            const thinkingContainer = this.createThinkingContainer(finalThinking, true);
            msgEl.insertBefore(thinkingContainer, msgEl.querySelector('.message-content'));
        }

        // Handle Sources Dropdown
        const existingSources = msgEl.querySelector('.sources-container');
        if (existingSources) existingSources.remove();

        const sourcesContainer = this.createSourcesContainer(displayContent);
        if (sourcesContainer) {
            msgEl.insertBefore(sourcesContainer, msgEl.querySelector('.message-meta') || null);
        }

        // Handle Tool Badge and Timestamp
        let metaEl = msgEl.querySelector('.message-meta');
        if (!metaEl) {
            metaEl = document.createElement('div');
            metaEl.className = 'message-meta';
            msgEl.appendChild(metaEl);
        }

        if (hasTools && !metaEl.querySelector('.tool-badge')) {
            const badge = document.createElement('span');
            badge.className = 'tool-badge';
            badge.textContent = '🛠️ Tool Used';
            metaEl.insertBefore(badge, metaEl.firstChild);
        }
        if (timestamp && !metaEl.querySelector('.message-time')) {
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

        if (message.thinking) {
            div.appendChild(this.createThinkingContainer(message.thinking, true));
        }

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = this.formatContent(message.content || '');
        div.appendChild(contentDiv);


        const sourcesContainer = this.createSourcesContainer(message.content || '');
        if (sourcesContainer) {
            div.appendChild(sourcesContainer);
        }

        if (message.role === 'assistant') {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'message-meta';

            if (message.has_tools === true) {
                const badge = document.createElement('span');
                badge.className = 'tool-badge';
                badge.textContent = '🛠️ Tool Used';
                metaDiv.appendChild(badge);
            }

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

        // Process tables first (before other formatting)
        const lines = formatted.split('\n');
        const processed = [];
        let inTable = false;
        let tableRows = [];

        for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
                inTable = true;
                tableRows.push(trimmed);
            } else {
                if (inTable && tableRows.length > 0) {
                    processed.push(this.renderTable(tableRows));
                    tableRows = [];
                }
                inTable = false;
                processed.push(line);
            }
        }
        if (inTable && tableRows.length > 0) {
            processed.push(this.renderTable(tableRows));
        }
        formatted = processed.join('\n');

        // Headers (must be at start of line)
        formatted = formatted.replace(/^### (.+)$/gm, '<h4>$1</h4>');
        formatted = formatted.replace(/^## (.+)$/gm, '<h3>$1</h3>');
        formatted = formatted.replace(/^# (.+)$/gm, '<h2>$1</h2>');

        // Code blocks
        formatted = formatted.replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
        formatted = formatted.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Bold and italic
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');

        // Links
        formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

        // Lists (simple)
        formatted = formatted.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
        formatted = formatted.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

        // Line breaks
        formatted = formatted.replace(/\n/g, '<br>');

        return formatted;
    }

    renderTable(rows) {
        if (rows.length < 2) return rows.join('\n');

        const parseRow = (row) => row.split('|').slice(1, -1).map(cell => cell.trim());
        const headers = parseRow(rows[0]);
        const isHeaderRow = (row) => row.split('|').slice(1, -1).every(cell => /^[\-\s:]+$/.test(cell));

        let html = '<div class="table-wrapper"><table class="md-table">';

        // Header
        html += '<thead><tr>';
        for (const h of headers) {
            html += `<th>${h}</th>`;
        }
        html += '</tr></thead>';

        // Body
        html += '<tbody>';
        for (let i = 1; i < rows.length; i++) {
            if (isHeaderRow(rows[i])) continue;
            const cells = parseRow(rows[i]);
            html += '<tr>';
            for (const c of cells) {
                html += `<td>${c}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table></div>';

        return html;
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
