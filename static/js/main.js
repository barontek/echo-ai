// Echo AI - Main Application Entry Point
// Modern modular structure with all original features preserved

import { appState } from './state.js';
import { api } from './services/api.js';
import { wsService } from './services/websocket.js';
import {
    renderMessage,
    renderEmptyState,
    renderSessions,
    showError,
    showConnectionBanner,
    ensureBotMessage,
    updateThinkingElement,
    updateContentElement,
    finishMessageElement,
    updateSessionTitle,
    extractThinkingLocally,
} from './components/ui.js';

class EchoAI {
    constructor() {
        this.isMobileView = window.matchMedia('(max-width: 900px)');
        this.renderScheduled = false;
        this.init();
    }

    async init() {
        this.bindEvents();
        this.setLoadingModels();
        const hasModels = await this.loadModels();
        this.loadSessions();
        this.applyTheme();

        if (appState.state.currentSession) {
            this.loadSession(appState.state.currentSession);
        }

        if (hasModels) {
            const model = document.getElementById('ollama-model')?.value || 'qwen3:4b-instruct';
            wsService.connect(model, appState.state.currentSession);
        } else {
            this.showError('No models found. Please check if Ollama is running.');
        }

        this.updateMetrics();
        this.syncSidebarWithViewport();

        // Focus main content for screen readers
        document.getElementById('main-content')?.focus();
    }

    // -------------------------------------------------------------------------
    // Screen Reader Announcements
    // -------------------------------------------------------------------------

    announce(message, priority = 'polite') {
        const announcer = document.getElementById('sr-announcer');
        if (!announcer) return;

        announcer.setAttribute('aria-live', priority);
        announcer.textContent = '';
        setTimeout(() => {
            announcer.textContent = message;
        }, 100);
    }

    // -------------------------------------------------------------------------
    // Event Binding
    // -------------------------------------------------------------------------

    bindEvents() {
        document.getElementById('chat-form')?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendMessage();
        });

        document.getElementById('theme-toggle')?.addEventListener('change', (e) => {
            appState.setState({ theme: e.target.checked ? 'dark' : 'light' });
            localStorage.setItem('theme', appState.state.theme);
            this.applyTheme();
        });

        document.getElementById('new-chat-btn')?.addEventListener('click', () => this.newChat());
        document.getElementById('delete-session-btn')?.addEventListener('click', () => this.deleteCurrentSession());
        document.getElementById('rename-session-btn')?.addEventListener('click', () => this.renameCurrentSession());
        document.getElementById('purge-sessions-btn')?.addEventListener('click', () => this.purgeSessions());
        document.getElementById('ollama-model')?.addEventListener('change', (e) => this.updateModel(e.target.value));
        document.getElementById('stop-btn')?.addEventListener('click', () => this.stopGeneration());
        document.getElementById('session-search')?.addEventListener('input', () => this.loadSessions());
        document.getElementById('open-workflows-btn')?.addEventListener('click', () => this.openWorkflowsWindow());

        document.getElementById('sidebar-toggle')?.addEventListener('click', () => this.toggleSidebar());

        this.isMobileView.addEventListener('change', () => this.syncSidebarWithViewport());

        document.querySelector('.main')?.addEventListener('click', () => {
            if (this.isMobileView.matches && document.querySelector('.app')?.classList.contains('sidebar-open')) {
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

        document.getElementById('chat-container')?.addEventListener('click', (e) => {
            const header = e.target.closest('.thinking-header');
            if (!header) return;
            const content = header.nextElementSibling;
            content.classList.toggle('collapsed');
            const icon = header.querySelector('.thinking-icon');
            icon.textContent = content.classList.contains('collapsed') ? '▶' : '▼';
        });

        // Session list click delegation
        document.getElementById('session-list')?.addEventListener('click', (e) => {
            const item = e.target.closest('.session-item');
            if (item && item.title) {
                this.loadSession(item.title);
            }
        });

        // Quick action buttons
        document.querySelectorAll('[data-prompt]').forEach((btn) => {
            btn.addEventListener('click', () => {
                document.getElementById('chat-input').value = btn.dataset.prompt;
                this.sendMessage();
            });
        });

        // Setup WebSocket callbacks
        this.setupWebSocketCallbacks();
    }

    // -------------------------------------------------------------------------
    // WebSocket Setup
    // -------------------------------------------------------------------------

    setupWebSocketCallbacks() {
        wsService.onConnect = () => {
            showConnectionBanner('Connected', false);
        };

        wsService.onDisconnect = () => {
            this.setConnectionStatus(false);
            showConnectionBanner('Disconnected. Reconnecting...', true);
        };

        wsService.onError = () => {
            this.setConnectionStatus(false);
        };

        wsService.onMessage = (data) => this.handleWebSocketMessage(data);
    }

    handleWebSocketMessage(data) {
        // Track session ID from server
        if (data.session_id && data.session_id !== appState.state.currentSession) {
            appState.setState({ currentSession: data.session_id });
            localStorage.setItem('currentSession', data.session_id);
            this.loadSessions();
        }

        // Handle title update
        if (data.title && data.session_id === appState.state.currentSession) {
            updateSessionTitle(data.session_id, data.title);
            this.loadSessions();
        }

        switch (data.type) {
            case 'ready':
                // Send buffered message when ready
                if (appState.state.pendingUserMessage) {
                    wsService.sendMessage(appState.state.pendingUserMessage);
                    appState.setState({ pendingUserMessage: null });
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

            case 'content':
                if (!appState.state.streamMetrics.firstTokenMs) {
                    appState.setState({
                        streamMetrics: {
                            ...appState.state.streamMetrics,
                            firstTokenMs: performance.now()
                        }
                    });
                }
                appState.setState({ pendingContent: data.content });
                this.scheduleRender();
                break;

            case 'done':
                this.flushPendingRender();
                this.finishMessage(data.content, data.thinking, data.timestamp, data.has_tools, data.tool_calls);
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
        const container = document.getElementById('chat-container');
        if (!container) return;

        if (appState.state.pendingThinking !== null && appState.state.pendingThinking !== undefined) {
            updateThinkingElement(container, appState.state.pendingThinking);
        }
        if (appState.state.pendingContent !== null && appState.state.pendingContent !== undefined) {
            const { displayContent } = extractThinkingLocally(appState.state.pendingContent);
            updateContentElement(container, displayContent);
            this.smartScroll();
        }
    }

    // -------------------------------------------------------------------------
    // API Methods
    // -------------------------------------------------------------------------

    async loadModels() {
        try {
            const data = await api.fetchModels();
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
            const data = await api.fetchSessions();
            renderSessions(data.sessions, appState.state.currentSession);
        } catch {
            renderSessions([], appState.state.currentSession);
        }
    }

    async newChat() {
        appState.setState({ currentSession: null, messages: [], pendingContent: null, pendingThinking: null });
        localStorage.removeItem('currentSession');
        wsService.sessionId = null;
        wsService.reconnectWithNewSession();
        this.renderMessages();
        this.loadSessions();
        this.closeSidebarOnMobile();
        this.announce('New chat started');
        document.getElementById('chat-input')?.focus();
    }

    async loadSession(sessionId) {
        try {
            const data = await api.loadSession(sessionId);
            appState.setState({
                currentSession: sessionId,
                messages: data.messages || [],
            });
            localStorage.setItem('currentSession', sessionId);
            this.renderMessages();
            this.loadSessions();
            this.closeSidebarOnMobile();

            const msgCount = data.messages?.length || 0;
            this.announce(`Loaded session with ${msgCount} messages`);

            // Reconnect WebSocket with session
            const model = document.getElementById('ollama-model')?.value || 'qwen3:4b-instruct';
            wsService.reconnectWithNewSession();
            wsService.sessionId = sessionId;
        } catch (e) {
            console.error('Failed to load session:', e);
        }
    }

    async deleteCurrentSession() {
        if (!appState.state.currentSession) return;
        if (!confirm('Delete this session?')) return;

        try {
            await api.deleteSession(appState.state.currentSession);
            appState.setState({ currentSession: null, messages: [] });
            localStorage.removeItem('currentSession');
            this.renderMessages();
            this.loadSessions();
            this.closeSidebarOnMobile();
            this.announce('Session deleted');
        } catch (e) {
            console.error('Failed to delete session:', e);
        }
    }

    async renameCurrentSession() {
        if (!appState.state.currentSession) return;
        const currentItem = document.querySelector('.session-item.active');
        const currentTitle = currentItem ? currentItem.textContent : appState.state.currentSession;
        const newTitle = prompt('Rename session to:', currentTitle);
        if (!newTitle || newTitle === currentTitle) return;

        try {
            await api.renameSession(appState.state.currentSession, newTitle);
            this.loadSessions();
        } catch (e) {
            console.error('Failed to rename session:', e);
        }
    }

    async purgeSessions() {
        if (!confirm('Are you sure you want to purge ALL session history? This cannot be undone.')) return;

        try {
            const data = await api.purgeSessions();
            appState.setState({ currentSession: null, messages: [] });
            localStorage.removeItem('currentSession');
            this.renderMessages();
            this.loadSessions();
            alert(`Successfully purged ${data.purged_count} sessions.`);
        } catch (e) {
            console.error('Failed to purge sessions:', e);
            this.showError('Failed to purge sessions.');
        }
    }

    async updateModel(model) {
        appState.setState({ model });
        document.getElementById('model-badge').textContent = `Model: ${model}`;

        if (!appState.state.isStreaming) {
            wsService.model = model;
            wsService.reconnectWithNewSession();
        }
    }

    // -------------------------------------------------------------------------
    // Message Handling
    // -------------------------------------------------------------------------

    sendMessage() {
        if (appState.state.isStreaming) return;

        const input = document.getElementById('chat-input');
        const content = input.value.trim();
        if (!content) return;

        input.value = '';

        const timestamp = new Date().toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        });

        this.addMessage('user', content, timestamp);

        appState.setState({
            isStreaming: true,
            streamMetrics: { startMs: performance.now(), firstTokenMs: 0 },
            pendingContent: null,
            pendingThinking: null,
        });

        this.setStopButtonVisible(true);

        if (wsService.isConnected) {
            wsService.sendMessage(content);
        } else {
            appState.setState({ pendingUserMessage: content });
        }
    }

    stopGeneration() {
        wsService.sendStop();
        this.resetButtons();
    }

    addMessage(role, content, timestamp = '') {
        const container = document.getElementById('chat-container');
        const messages = [...appState.state.messages, { role, content, timestamp }];
        appState.setState({ messages });
        renderMessage({ role, content, timestamp }, container);
        this.smartScroll();
        this.updateMetrics();
    }

    updateThinking(thinking) {
        appState.setState({ pendingThinking: thinking });
    }

    finishMessage(rawContent, backendThinking, timestamp, hasTools, toolCalls = []) {
        this.resetButtons();

        const container = document.getElementById('chat-container');
        if (!container) return;

        // Extract thinking from content
        const { displayContent, thinking } = extractThinkingLocally(rawContent);
        const finalThinking = backendThinking || thinking;

        // Ensure we have a bot message
        ensureBotMessage(container);

        const messages = [...appState.state.messages];
        const lastMsg = messages[messages.length - 1];

        if (lastMsg && lastMsg.role === 'assistant') {
            lastMsg.content = displayContent;
            lastMsg.thinking = finalThinking;
            lastMsg.tool_calls = toolCalls;
            lastMsg.timestamp = timestamp || lastMsg.timestamp || new Date().toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit'
            });
        }

        appState.setState({ messages, isStreaming: false });

        // Update the DOM element
        finishMessageElement(container, {
            content: displayContent,
            thinking: finalThinking,
            tool_calls: toolCalls,
            timestamp: timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        });

        this.smartScroll(true);

        // Update metrics
        const total = Math.round(performance.now() - appState.state.streamMetrics.startMs);
        const ttfb = appState.state.streamMetrics.firstTokenMs
            ? Math.round(appState.state.streamMetrics.firstTokenMs - appState.state.streamMetrics.startMs)
            : total;
        this.updateMetrics({ ttfb, total });
    }

    // -------------------------------------------------------------------------
    // UI Rendering
    // -------------------------------------------------------------------------

    /**
     * Merge tool-only assistant messages with the next assistant message.
     * e.g., message with tool_calls + empty content followed by message with actual content
     */
    mergeToolMessages(messages) {
        const merged = [];
        let i = 0;

        while (i < messages.length) {
            const current = messages[i];

            // Check if this is an assistant message with tool_calls but empty content
            if (
                current.role === 'assistant' &&
                current.tool_calls &&
                current.tool_calls.length > 0 &&
                !current.content
            ) {
                // Look for the next assistant message with actual content
                const nextAssistant = messages.slice(i + 1).find(m => m.role === 'assistant' && m.content);

                if (nextAssistant) {
                    // Merge tool_calls into the next message
                    const mergedToolCalls = [...(nextAssistant.tool_calls || [])];
                    for (const tc of current.tool_calls) {
                        if (!mergedToolCalls.some(t => t.name === tc.name)) {
                            mergedToolCalls.push(tc);
                        }
                    }
                    nextAssistant.tool_calls = mergedToolCalls;
                    // Skip the empty message
                    i++;
                    continue;
                }
            }

            merged.push(current);
            i++;
        }

        return merged;
    }

    renderMessages() {
        const container = document.getElementById('chat-container');
        if (!container) return;

        container.innerHTML = '';

        if (appState.state.messages.length === 0) {
            renderEmptyState(container);
            this.updateMetrics();
            return;
        }

        const windowSize = 120;
        const start = Math.max(0, appState.state.messages.length - windowSize);
        let visibleMessages = appState.state.messages.slice(start);

        // Merge tool-only messages with next assistant message
        visibleMessages = this.mergeToolMessages(visibleMessages);

        visibleMessages.forEach((msg) => renderMessage(msg, container));
        this.smartScroll(true);
        this.updateMetrics();
    }

    updateMetrics(extra = null) {
        const msgCount = appState.state.messages.length;
        const badge = document.getElementById('metrics-badge');
        if (!badge) return;

        if (!extra) {
            badge.textContent = `Messages: ${msgCount}`;
        } else {
            badge.textContent = `Messages: ${msgCount} · TTFB: ${extra.ttfb}ms · Total: ${extra.total}ms`;
        }
    }

    applyTheme() {
        document.documentElement.setAttribute('data-theme', appState.state.theme);
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            toggle.checked = appState.state.theme === 'dark';
        }
    }

    setLoadingModels() {
        const select = document.getElementById('ollama-model');
        if (select) {
            select.innerHTML = '<option>Loading models...</option>';
        }
    }

    setConnectionStatus(connected) {
        const indicator = document.getElementById('model-badge');
        if (indicator) {
            indicator.textContent = connected
                ? `Model: ${appState.state.model}`
                : 'Disconnected';
        }
    }

    setStopButtonVisible(visible) {
        const stopBtn = document.getElementById('stop-btn');
        const sendBtn = document.getElementById('send-btn');
        if (stopBtn) stopBtn.style.display = visible ? 'inline-block' : 'none';
        if (sendBtn) sendBtn.style.display = visible ? 'none' : 'inline-block';
    }

    resetButtons() {
        appState.setState({ isStreaming: false });
        this.setStopButtonVisible(false);
        document.querySelectorAll('.message.streaming').forEach(m => m.classList.remove('streaming'));
    }

    smartScroll(force = false) {
        const container = document.getElementById('chat-container');
        if (!container) return;

        const distance = container.scrollHeight - container.scrollTop - container.clientHeight;
        if (force || distance < 120) {
            container.scrollTop = container.scrollHeight;
        }
    }

    // -------------------------------------------------------------------------
    // Sidebar
    // -------------------------------------------------------------------------

    syncSidebarWithViewport() {
        const app = document.querySelector('.app');
        if (!this.isMobileView.matches) {
            app?.classList.remove('sidebar-open');
        }
        this.updateSidebarToggleAria();
    }

    toggleSidebar(forceOpen) {
        const app = document.querySelector('.app');
        if (typeof forceOpen === 'boolean') {
            app?.classList.toggle('sidebar-open', forceOpen);
        } else {
            app?.classList.toggle('sidebar-open');
        }
        this.updateSidebarToggleAria();
    }

    closeSidebarOnMobile() {
        if (!this.isMobileView.matches) return;
        this.toggleSidebar(false);
    }

    updateSidebarToggleAria() {
        const toggle = document.getElementById('sidebar-toggle');
        const isOpen = document.querySelector('.app')?.classList.contains('sidebar-open');
        toggle?.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }

    // -------------------------------------------------------------------------
    // Workflows
    // -------------------------------------------------------------------------

    openWorkflowsWindow() {
        window.open('/workflows', '_blank', 'noopener,noreferrer');
    }

    // -------------------------------------------------------------------------
    // Error Handling
    // -------------------------------------------------------------------------

    showError(message) {
        appState.setState({ isStreaming: false });
        this.resetButtons();
        const container = document.getElementById('chat-container');
        if (container) showError(container, message);
        this.smartScroll(true);
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    window.echoAI = new EchoAI();
});
