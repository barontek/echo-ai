import pytest
import respx
import httpx
from src.agentframework.tools.api import RESTAPITool
from src.agentframework.safety import SafetyConfig

@pytest.fixture
def api_tool():
    return RESTAPITool(safety_config=SafetyConfig(allow_network=True))

@pytest.fixture
def blocked_api_tool():
    return RESTAPITool(safety_config=SafetyConfig(allow_network=False))

@pytest.mark.asyncio
@respx.mock
async def test_rest_api_get(api_tool):
    respx.get("https://api.example.com/data?page=1").mock(return_value=httpx.Response(200, json={"items": [1, 2, 3]}))

    res = await api_tool.execute(
        method="GET",
        url="https://api.example.com/data",
        query_params={"page": "1"}
    )
    assert not res.error
    assert "Status Code: 200" in res.content
    assert '"items": [' in res.content

@pytest.mark.asyncio
@respx.mock
async def test_rest_api_post(api_tool):
    respx.post("https://api.example.com/create").mock(return_value=httpx.Response(201, text="Created Successfully"))

    res = await api_tool.execute(
        method="POST",
        url="https://api.example.com/create",
        json_body={"name": "test"},
        headers={"Authorization": "Bearer token"}
    )
    assert not res.error
    assert "Status Code: 201" in res.content
    assert "Created Successfully" in res.content

@pytest.mark.asyncio
async def test_rest_api_blocked_network(blocked_api_tool):
    res = await blocked_api_tool.execute("GET", "https://api.example.com")
    assert "Network blocked" in res.error

@pytest.mark.asyncio
async def test_rest_api_invalid_method(api_tool):
    res = await api_tool.execute("INVALID", "https://api.example.com")
    assert "Unsupported HTTP method" in res.error

@pytest.mark.asyncio
@respx.mock
async def test_rest_api_timeout(api_tool):
    respx.get("https://api.example.com").mock(side_effect=httpx.TimeoutException("Timeout"))
    res = await api_tool.execute("GET", "https://api.example.com")
    assert "timed out" in res.error
