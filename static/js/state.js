// State management module

export class Store {
    constructor(initialState = {}) {
        this._state = initialState;
        this._listeners = new Map();
    }

    get state() {
        return this._state;
    }

    setState(updates) {
        const prev = { ...this._state };
        this._state = { ...this._state, ...updates };

        // Notify listeners
        for (const [key, listeners] of this._listeners) {
            if (key in updates) {
                listeners.forEach(fn => fn(this._state[key], prev[key]));
            }
        }
    }

    subscribe(key, callback) {
        if (!this._listeners.has(key)) {
            this._listeners.set(key, new Set());
        }
        this._listeners.get(key).add(callback);

        // Return unsubscribe function
        return () => {
            this._listeners.get(key)?.delete(callback);
        };
    }
}

// Application state store
export const appState = new Store({
    ws: null,
    messages: [],
    currentSession: localStorage.getItem('currentSession') || null,
    isStreaming: false,
    theme: localStorage.getItem('theme') || 'dark',
    reconnectTimer: null,
    pendingContent: null,
    pendingThinking: null,
    pendingUserMessage: null,
    streamMetrics: { startMs: 0, firstTokenMs: 0 },
    isMobileView: window.matchMedia('(max-width: 900px)').matches,
    renderScheduled: false,
    model: 'qwen3:4b-instruct',
});

// State keys for type safety
export const StateKeys = {
    WS: 'ws',
    MESSAGES: 'messages',
    CURRENT_SESSION: 'currentSession',
    IS_STREAMING: 'isStreaming',
    THEME: 'theme',
    RECONNECT_TIMER: 'reconnectTimer',
    PENDING_CONTENT: 'pendingContent',
    PENDING_THINKING: 'pendingThinking',
    PENDING_USER_MESSAGE: 'pendingUserMessage',
    STREAM_METRICS: 'streamMetrics',
    IS_MOBILE_VIEW: 'isMobileView',
    RENDER_SCHEDULED: 'renderScheduled',
    MODEL: 'model',
};
