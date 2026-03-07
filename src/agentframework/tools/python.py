"""Tool for checking executing Python code."""

import asyncio
import os
import sys
import tempfile
from pydantic import BaseModel, Field

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult


class PythonExecParams(BaseModel):
    """Parameters for PythonTool."""

    code: str = Field(description="The Python code to execute. Use print() to output results.")


class PythonTool(Tool):
    """Execute Python code in a sandboxed subprocess and return stdout/stderr."""

    parameters_model = PythonExecParams

    def __init__(self, safety_config: SafetyConfig | None = None, execution_timeout: int = 10):
        super().__init__(
            name="python_execute",
            description="Executes a Python script and returns the stdout and stderr. Use this for math, data analysis, or interacting with local files. You must use print() to see the results of your code.",
        )
        self.execution_timeout = execution_timeout

        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(require_approval_for=["python_execute"]))

    async def execute(self, code: str, **kwargs) -> ToolResult:
        """Execute the provided Python code."""
        if self.validator.requires_approval("python_execute"):
            approved = self.validator.get_approval(
                "python_execute", f"\n```python\n{code}\n```\n"
            )
            if not approved:
                return ToolResult(error="Python execution requires approval")

        # Create a temporary file to hold the code
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            # Use the same python executable running the agent
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Isolate the environment slightly, though this isn't a true sandbox
                env={"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.execution_timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                # Wait for the kill to finish
                await process.communicate()
                return ToolResult(
                    error=f"Execution timed out after {self.execution_timeout} seconds. Code might be stuck in an infinite loop."
                )

            stdout_str = stdout.decode().strip()
            stderr_str = stderr.decode().strip()

            output = ""
            if stdout_str:
                output += f"STDOUT:\n{stdout_str}\n"
            if stderr_str:
                output += f"STDERR:\n{stderr_str}\n"

            if not output:
                output = "Code executed successfully with no output (did you forget to use print()?)."

            # Truncate if output is excessively large to protect context window
            if len(output) > 20000:
                output = output[:20000] + "\n\n... (Output truncated due to length limits)"

            if process.returncode != 0:
                return ToolResult(
                    content=output,
                    error=f"Process exited with non-zero code {process.returncode}"
                )

            return ToolResult(content=output)

        except Exception as e:
            return ToolResult(error=f"Failed to execute python code: {e}")
        finally:
            # Clean up the temporary file
            try:
                os.remove(temp_path)
            except OSError:
                pass
