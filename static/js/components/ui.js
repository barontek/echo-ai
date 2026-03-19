// UI Components module - rendering functions for chat UI

// Common tool names for detection
const TOOL_NAMES = new Set([
    'bash', 'web_search', 'web_fetch', 'read_file', 'write_file', 'grep', 'glob',
    'list_dir', 'search', 'notes', 'memory', 'call', 'create_directory',
    'delete_file', 'rename', 'move', 'copy', 'patch', 'apply', 'list',
    'move_to_trash', 'restore', 'read', 'write', 'find', 'ls', 'dir', 'cat',
    'head', 'tail', 'wc', 'sort', 'uniq', 'cut', 'awk', 'sed', 'git', 'pip',
    'npm', 'make', 'docker', 'curl', 'wget', 'ssh', 'python', 'execute'
]);

// -------------------------------------------------------------------------
// Content Formatting
// -------------------------------------------------------------------------

export function formatContent(content) {
    if (!content) return '';
    try {
        const html = marked.parse(content, { gfm: true, breaks: true });
        const clean = DOMPurify.sanitize(html, {
            ADD_TAGS: ['pre', 'code'],
            ADD_ATTR: ['class'],
        });
        return clean;
    } catch (e) {
        return escapeHtml(content);
    }
}

/**
 * Extract tool usage from the START of content.
 * Returns { toolNames: [], content: cleanedContent }
 * Tool names and their JSON args at the start of content are extracted and removed.
 */
export function extractToolUsageFromContent(content) {
    if (!content) return { toolNames: [], content: content };

    const lines = content.split('\n');
    const toolNames = [];
    const remainingLines = [];
    let i = 0;

    // Skip tool name lines at the start (e.g., "web_search" or "bash")
    while (i < lines.length) {
        const line = lines[i].trim();
        if (!line) {
            i++;
            continue;
        }
        if (TOOL_NAMES.has(line)) {
            toolNames.push(line);
            i++;
        } else {
            break;
        }
    }

    // Skip JSON argument lines that follow tool names
    while (i < lines.length) {
        const line = lines[i].trim();
        if (line.startsWith('{') || line.startsWith('"')) {
            i++;
        } else {
            break;
        }
    }

    remainingLines.push(...lines.slice(i));

    // Clean up: remove empty lines at start and collapse multiple newlines
    while (remainingLines.length > 0 && !remainingLines[0].trim()) {
        remainingLines.shift();
    }

    const cleaned = remainingLines.join('\n').replace(/\n{3,}/g, '\n\n').trim();

    return { toolNames, content: cleaned };
}

export function highlightCode(container) {
    if (typeof Prism !== 'undefined' && Prism.highlightAllUnder) {
        Prism.highlightAllUnder(container);
    }
}

export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// -------------------------------------------------------------------------
// Thinking Parsing
// -------------------------------------------------------------------------

export function extractThinkingLocally(content) {
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

// -------------------------------------------------------------------------
// Component Creators
// -------------------------------------------------------------------------

export function createThinkingContainer(thinking, collapsed = false) {
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

export function createToolsContainer(toolCalls) {
    if (!toolCalls || toolCalls.length === 0) return null;

    const container = document.createElement('div');
    container.className = 'tools-inline';

    const toolNames = toolCalls.map(t => t.name).join(', ');
    container.innerHTML = `
        <button type="button" class="tools-toggle" aria-expanded="false">
            <span class="tools-icon">▶</span> 🛠️ ${escapeHtml(toolNames)}
        </button>
        <div class="tools-details" style="display: none;">
            ${toolCalls.map((tc) => `
                <div class="tool-item">
                    <strong>${escapeHtml(tc.name)}</strong>
                    <pre><code>${escapeHtml(JSON.stringify(tc.arguments, null, 2))}</code></pre>
                </div>
            `).join('')}
        </div>
    `;

    container.querySelector('.tools-toggle').addEventListener('click', (e) => {
        const details = container.querySelector('.tools-details');
        const icon = container.querySelector('.tools-icon');
        const isExpanded = details.style.display !== 'none';
        details.style.display = isExpanded ? 'none' : 'block';
        icon.textContent = isExpanded ? '▶' : '▼';
        e.currentTarget.setAttribute('aria-expanded', !isExpanded);
    });

    return container;

    return container;
}

export function createSourcesContainer(content) {
    const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g;
    const links = [];
    let match;
    while ((match = linkRegex.exec(content)) !== null) {
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
            ${links.map(link =>
                `<a href="${link.url}" target="_blank" rel="noopener noreferrer">🔗 ${escapeHtml(link.text)}</a>`
            ).join('')}
        </div>
    `;

    const header = container.querySelector('.sources-header');
    const contentDiv = container.querySelector('.sources-content');
    const icon = container.querySelector('.sources-icon');
    header.addEventListener('click', () => {
        contentDiv.classList.toggle('collapsed');
        icon.textContent = contentDiv.classList.contains('collapsed') ? '▼' : '▶';
    });

    return container;
}

// -------------------------------------------------------------------------
// Message Rendering
// -------------------------------------------------------------------------

export function renderEmptyState(container) {
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
    return container;
}

export function renderMessage(message, container) {
    const emptyState = container.querySelector('.empty-state');
    if (emptyState) emptyState.remove();

    // Extract tool usage from content start (for models that output tool names as text)
    const { toolNames: extractedTools, content: cleanedContent } =
        extractToolUsageFromContent(message.content || '');

    // Merge with existing tool_calls
    const toolCalls = [...(message.tool_calls || [])];
    for (const name of extractedTools) {
        if (!toolCalls.some(tc => tc.name === name)) {
            toolCalls.push({ name, arguments: {} });
        }
    }

    const div = document.createElement('div');
    div.className = `message message-${message.role === 'user' ? 'user' : 'bot'}`;

    if (message.thinking) {
        div.appendChild(createThinkingContainer(message.thinking, true));
    }

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.innerHTML = formatContent(cleanedContent);
    highlightCode(contentDiv);
    div.appendChild(contentDiv);

    const sourcesContainer = createSourcesContainer(cleanedContent);
    if (sourcesContainer) {
        div.appendChild(sourcesContainer);
    }

    if (message.role === 'assistant') {
        const toolsContainer = createToolsContainer(toolCalls);
        if (toolsContainer) {
            div.appendChild(toolsContainer);
        }

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
    return div;
}

export function ensureBotMessage(container) {
    const lastMessage = container.querySelector('.message:last-child');
    if (!lastMessage || lastMessage.classList.contains('message-user')) {
        const msgDiv = document.createElement('div');
        msgDiv.className = 'message message-bot streaming';
        container.appendChild(msgDiv);
        return msgDiv;
    }
    lastMessage.classList.add('streaming');
    return lastMessage;
}

export function updateThinkingElement(container, thinking) {
    const lastMsg = container.querySelector('.message:last-child');
    if (!lastMsg) return;

    let thinkingContainer = lastMsg.querySelector('.thinking-container');
    if (!thinkingContainer) {
        thinkingContainer = createThinkingContainer('');
        const contentEl = lastMsg.querySelector('.message-content');
        lastMsg.insertBefore(thinkingContainer, contentEl);
    }

    thinkingContainer.querySelector('.thinking-content').textContent = thinking;
}

export function updateContentElement(container, content) {
    const contentEl = container.querySelector('.message:last-child .message-content');
    if (contentEl) {
        contentEl.innerHTML = formatContent(content);
        highlightCode(contentEl);
    }
}

export function finishMessageElement(container, message, extra = {}) {
    const msgEl = container.querySelector('.message:last-child');
    if (!msgEl) return;

    msgEl.classList.remove('streaming');

    // Extract tool usage from content start
    const { toolNames: extractedTools, content: rawContent } =
        extractToolUsageFromContent(message.content || '');

    // Merge with existing tool_calls
    const toolCalls = [...(message.tool_calls || [])];
    for (const name of extractedTools) {
        if (!toolCalls.some(tc => tc.name === name)) {
            toolCalls.push({ name, arguments: {} });
        }
    }

    // Update content
    const contentEl = msgEl.querySelector('.message-content');
    if (contentEl && rawContent !== undefined) {
        contentEl.innerHTML = formatContent(rawContent);
        highlightCode(contentEl);
    }

    // Handle thinking
    const { displayContent, thinking } = extractThinkingLocally(rawContent);
    const finalThinking = message.thinking || thinking;

    if (finalThinking) {
        updateThinkingElement(container, finalThinking);

        // If thinking container doesn't exist yet, create it
        if (!msgEl.querySelector('.thinking-container')) {
            const thinkingContainer = createThinkingContainer(finalThinking, true);
            const contentEl = msgEl.querySelector('.message-content');
            msgEl.insertBefore(thinkingContainer, contentEl);
        }
    }

    // Remove existing sources/tools
    const existingSources = msgEl.querySelector('.sources-container');
    if (existingSources) existingSources.remove();

    const existingTools = msgEl.querySelector('.tools-container, .tools-inline');
    if (existingTools) existingTools.remove();

    // Add sources
    const sourcesContainer = createSourcesContainer(displayContent);
    if (sourcesContainer) {
        const metaEl = msgEl.querySelector('.message-meta');
        metaEl ? msgEl.insertBefore(sourcesContainer, metaEl) : msgEl.appendChild(sourcesContainer);
    }

    // Add tools
    const toolsContainer = createToolsContainer(toolCalls);
    if (toolsContainer) {
        const metaEl = msgEl.querySelector('.message-meta');
        metaEl ? msgEl.insertBefore(toolsContainer, metaEl) : msgEl.appendChild(toolsContainer);
    }

    // Add/update metadata
    let metaEl = msgEl.querySelector('.message-meta');
    if (!metaEl) {
        metaEl = document.createElement('div');
        metaEl.className = 'message-meta';
        msgEl.appendChild(metaEl);
    }

    if (message.timestamp && !metaEl.querySelector('.message-time')) {
        const timeEl = document.createElement('span');
        timeEl.className = 'message-time';
        timeEl.textContent = message.timestamp;
        metaEl.appendChild(timeEl);
    }
}

// -------------------------------------------------------------------------
// Session Rendering
// -------------------------------------------------------------------------

export function renderSessions(sessions, currentSessionId) {
    const filter = document.getElementById('session-search')?.value.trim().toLowerCase() || '';
    const visibleSessions = sessions.filter((s) => {
        const titleMatch = s.title && s.title.toLowerCase().includes(filter);
        const idMatch = s.id && s.id.toLowerCase().includes(filter);
        return titleMatch || idMatch;
    });

    const container = document.getElementById('session-list');
    if (!container) return;

    container.innerHTML = '';
    if (visibleSessions.length === 0) {
        container.innerHTML = '<div class="session-item">No sessions</div>';
        return;
    }

    visibleSessions.forEach((session) => {
        const div = document.createElement('button');
        div.className = 'session-item' + (session.id === currentSessionId ? ' active' : '');
        div.textContent = session.title || session.id;
        div.title = session.id;
        div.type = 'button';
        container.appendChild(div);
    });
}

export function updateSessionTitle(sessionId, newTitle) {
    const sessionItems = document.querySelectorAll('.session-item');
    sessionItems.forEach(item => {
        if (item.title === sessionId) {
            item.textContent = newTitle;
        }
    });
}

// -------------------------------------------------------------------------
// Error Display
// -------------------------------------------------------------------------

export function showError(container, message) {
    const div = document.createElement('div');
    div.className = 'message message-bot';
    div.style.backgroundColor = '#ff4444';
    div.innerHTML = `<div class="message-content">Error: ${escapeHtml(message)}</div>`;
    container.appendChild(div);
}

// -------------------------------------------------------------------------
// Connection Banner
// -------------------------------------------------------------------------

export function showConnectionBanner(message, visible) {
    const banner = document.getElementById('connection-banner');
    if (banner) {
        banner.textContent = message;
        banner.style.display = visible ? 'block' : 'none';
    }
}
