# Chat Mode

Echo AI provides a modern, interactive web-based chat interface for natural language interactions with the AI agent.

## Web Interface

The web interface is the primary way to interact with Chat Mode. It supports real-time streaming, tool usage visualization, and session management.

### Key Features

- **Real-time Streaming**: Responses are streamed via WebSockets, providing immediate feedback.
- **Thought Process**: For models that support reasoning, the "Thought Process" section shows the agent's internal logic. This section is collapsible.
- **Tool used Badge**: When the agent uses a tool (like web search or bash), a badge indicates that a tool was used.
- **Sources Dropdown**: If the agent performs a web search, a "Sources" dropdown lists the referenced links.
- **Streaming Metrics**: Performance metrics including Time To First Byte (TTFB) and total generation time are displayed.
- **Mobile Support**: The interface is fully responsive, with a collapsible sidebar for smaller screens.

## How to Start

1. Ensure the backend server is running:
   ```bash
   python -m src.agentframework.web_api
   ```
2. Open your browser and navigate to the server address (default is `http://127.0.0.1:8501`).

## Session Management

- **Auto-titling**: The agent automatically generates a title for your session based on the initial conversation.
- **Rename/Delete**: You can manually rename or delete sessions from the sidebar.
- **Purge History**: A "Purge" option allows you to clear all session history.

## Technical Details

The web interface communicates with the FastAPI backend using:
- **REST API**: For configuration, session listing, and management.
- **WebSockets**: For real-time chat streaming and control (e.g., stopping generation).

### API Endpoints

- `GET /api/sessions`: List all available chat sessions.
- `POST /api/sessions`: Create a new session.
- `DELETE /api/sessions/{id}`: Delete a specific session.
- `POST /api/sessions/rename`: Rename an existing session.
- `WS /ws/chat`: WebSocket endpoint for interactive streaming chat.
