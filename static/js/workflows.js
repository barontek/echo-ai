class WorkflowWindow {
    constructor() {
        this.workflows = [];
        this.selectedWorkflowId = null;
        this.bindEvents();
        this.loadWorkflows();
    }

    bindEvents() {
        document.getElementById('workflow-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.runWorkflow();
        });
    }

    async loadWorkflows() {
        const response = await fetch('/api/workflows');
        const data = await response.json();
        this.workflows = data.workflows || [];

        if (this.workflows.length > 0) {
            this.selectedWorkflowId = this.workflows[0].id;
        }

        this.renderWorkflows();
    }

    renderWorkflows() {
        const container = document.getElementById('workflow-list');

        if (this.workflows.length === 0) {
            container.innerHTML = '<p class="workflow-item-description">No workflows available.</p>';
            return;
        }

        container.innerHTML = '';
        this.workflows.forEach((workflow) => {
            const item = document.createElement('button');
            item.type = 'button';
            item.className = `workflow-item ${workflow.id === this.selectedWorkflowId ? 'active' : ''}`;
            item.innerHTML = `
                <div class="workflow-item-title">${this.escapeHtml(workflow.title)}</div>
                <div class="workflow-item-description">${this.escapeHtml(workflow.description)}</div>
            `;
            item.addEventListener('click', () => {
                this.selectedWorkflowId = workflow.id;
                this.renderWorkflows();
            });
            container.appendChild(item);
        });
    }

    async runWorkflow() {
        if (!this.selectedWorkflowId) return;

        const topicEl = document.getElementById('workflow-topic');
        const outputEl = document.getElementById('workflow-output');
        const button = document.getElementById('run-workflow-btn');
        const topic = topicEl.value.trim();
        if (!topic) return;

        button.disabled = true;
        outputEl.textContent = 'Running workflow...';

        try {
            const response = await fetch('/api/workflows/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workflow_id: this.selectedWorkflowId, topic }),
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || 'Failed to run workflow');
            }

            outputEl.textContent = data.response || 'Workflow completed with no output.';
        } catch (error) {
            outputEl.textContent = `Error: ${error.message || 'Workflow execution failed'}`;
        } finally {
            button.disabled = false;
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

new WorkflowWindow();
