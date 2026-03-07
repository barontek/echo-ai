import pytest
from src.agentframework.tools.python import PythonTool
from src.agentframework.safety import SafetyConfig

@pytest.fixture
def allow_all_safety():
    return SafetyConfig(allow_network=True)

@pytest.mark.asyncio
async def test_python_tool_basic_print(allow_all_safety):
    tool = PythonTool(safety_config=allow_all_safety)
    res = await tool.execute(code="print('Hello World')")
    assert not res.error
    assert "STDOUT:\nHello World" in res.content

@pytest.mark.asyncio
async def test_python_tool_stderr(allow_all_safety):
    tool = PythonTool(safety_config=allow_all_safety)
    # Raising an exception should output to stderr
    res = await tool.execute(code="raise ValueError('Test Error')")
    assert res.error
    assert "Process exited with non-zero code" in res.error
    assert "STDERR" in res.content
    assert "ValueError: Test Error" in res.content

@pytest.mark.asyncio
async def test_python_tool_timeout(allow_all_safety):
    # Set a very short timeout for testing
    tool = PythonTool(safety_config=allow_all_safety, execution_timeout=1)
    res = await tool.execute(code="import time\ntime.sleep(2)")
    assert res.error and "Execution timed out" in res.error

@pytest.mark.asyncio
async def test_python_tool_no_output(allow_all_safety):
    tool = PythonTool(safety_config=allow_all_safety)
    res = await tool.execute(code="x = 1 + 1")
    assert not res.error
    assert "Code executed successfully with no output" in res.content
