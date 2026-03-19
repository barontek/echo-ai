// WebSocket service module - handles WebSocket connection with full features

export class WebSocketService {
    constructor() {
        this.ws = null;
        this.reconnectDelay = 1000;
        this.maxReconnectDelay = 30000;
        this.reconnectTimer = null;
        this.pendingMessage = null;
        this.model = null;
        this.sessionId = null;

        // Callbacks
        this.onMessage = null;
        this.onError = null;
        this.onConnect = null;
        this.onDisconnect = null;
        this.onReady = null;
        this.onTitleUpdate = null;
    }

    connect(model = 'qwen3:4b-instruct', sessionId = null) {
        this.model = model;
        this.sessionId = sessionId;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectDelay = 1000;
            this._clearReconnect();

            // Send model info on connect
            const payload = { provider: 'ollama', model: this.model };
            if (this.sessionId) {
                payload.session_id = this.sessionId;
            }
            this.ws.send(JSON.stringify(payload));

            this.onConnect?.();
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // Handle ping - respond with pong
                if (data.type === 'ping') {
                    this.ws.send(JSON.stringify({ type: 'pong' }));
                    return;
                }

                // Track session ID from server
                if (data.session_id && data.session_id !== this.sessionId) {
                    this.sessionId = data.session_id;
                }

                this.onMessage?.(data);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.onError?.(error);
            this._scheduleReconnect();
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.onDisconnect?.();
            this._scheduleReconnect();
        };
    }

    _scheduleReconnect() {
        if (this.reconnectTimer) return;
        let remaining = 3;

        this.reconnectTimer = setInterval(() => {
            remaining -= 1;
            if (remaining <= 0) {
                this._clearReconnect();
                this.connect(this.model, this.sessionId);
                return;
            }
        }, 1000);
    }

    _clearReconnect() {
        if (this.reconnectTimer) {
            clearInterval(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }

    reconnectWithNewSession() {
        if (this.ws) {
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.onmessage = null;
            this.ws.close();
        }
        this.sessionId = null;
        this.connect(this.model, null);
    }

    send(data) {
        if (this.ws?.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.warn('WebSocket not connected, buffering message');
            this.pendingMessage = data;
        }
    }

    sendMessage(content) {
        this.send({ content });
    }

    sendStop() {
        this.send({ type: 'stop' });
    }

    disconnect() {
        this._clearReconnect();
        if (this.ws) {
            this.ws.onclose = null;
            this.ws.onerror = null;
            this.ws.onmessage = null;
            this.ws.close();
            this.ws = null;
        }
    }

    get isConnected() {
        return this.ws?.readyState === WebSocket.OPEN;
    }
}

export const wsService = new WebSocketService();
