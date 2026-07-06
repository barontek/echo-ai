"""Tool for Human-in-the-loop (HITL) prompt interventions."""

import asyncio
from pydantic import BaseModel, Field
from . import Tool, ToolResult

class AskUserArgs(BaseModel):
    question: str = Field(..., description="The question or clarification to ask the human.")

class AskUserTool(Tool):
    """Tool to ask the human operator a question when the agent is stuck or needs confirmation."""

    parameters_model = AskUserArgs

    def __init__(self):
        super().__init__(
            name="ask_user",
            description="Use this tool to pause execution and ask the human operator a specific question. Wait for their answer before proceeding."
        )

    async def execute(self, question: str) -> ToolResult:
        """Execute the tool by prompting the user on standard input."""
        # For a clean CLI interface, we use rich if available, else fallback to print
        try:
            from rich.console import Console
            console = Console()
            console.print(f"[bold yellow]Agent Question:[/bold yellow] {question}")

            # Use to_thread to avoid blocking the async event loop with standard input
            answer = await asyncio.to_thread(input, "\nYour Answer: ")
        except ImportError:
            # Fallback for headless or non-rich environments
            print(f"\nAGENT QUESTION: {question}")
            answer = await asyncio.to_thread(input, "Your Answer: ")

        if not answer.strip():
            return ToolResult(content="The user provided an empty response. You must guess or fail.")

        return ToolResult(content=f"User answered: {answer}")
