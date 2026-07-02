"""Tool for making REST API calls."""

from typing import Any
from pydantic import BaseModel, Field

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult
from .web import get_http_client


class RESTAPIParams(BaseModel):
    """Parameters for RESTAPITool."""

    method: str = Field(description="HTTP method (GET, POST, PUT, DELETE, PATCH).")
    url: str = Field(description="The URL to send the request to.")
    headers: dict[str, str] | None = Field(
        default=None, description="Optional HTTP headers."
    )
    json_body: dict[str, Any] | None = Field(
        default=None, description="Optional JSON body for POST/PUT/PATCH requests."
    )
    query_params: dict[str, str] | None = Field(
        default=None, description="Optional URL query parameters."
    )


class RESTAPITool(Tool):
    """Make arbitrary REST API requests with network restrictions."""

    parameters_model = RESTAPIParams

    def __init__(self, safety_config: SafetyConfig | None = None):
        super().__init__(
            name="rest_api",
            description="Send REST API requests (GET, POST, PUT, DELETE) to external services. Can be used with JSON bodies and custom headers.",
        )

        if safety_config:
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(SafetyConfig(allow_network=True))

    async def execute(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        query_params: dict[str, str] | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute the REST API request."""
        import httpx
        import json

        method = method.upper()
        if method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            return ToolResult(error=f"Unsupported HTTP method: {method}")

        allowed, reason = self.validator.check_network_allowed(url)
        if not allowed:
            return ToolResult(error=f"Network blocked: {reason}")

        if method != "GET" and self.validator.requires_approval("rest_api"):
            approved = await self.validator.get_approval_async(
                "rest_api", f"API {method} to {url}\nBody: {json_body}"
            )
            if not approved:
                return ToolResult(error="API request requires approval")

        try:
            client = get_http_client()
            req = client.build_request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                params=query_params,
            )
            response = await client.send(req)

            content = f"Status Code: {response.status_code}\n\n"

            try:
                json_resp = response.json()
                content += json.dumps(json_resp, indent=2)
            except (json.JSONDecodeError, ValueError):
                text_resp = response.text
                if len(text_resp) > 20000:
                    text_resp = text_resp[:20000] + "\n... (truncated)"
                content += text_resp

            return ToolResult(content=content)

        except httpx.TimeoutException:
            return ToolResult(error="API Request timed out")
        except httpx.RequestError as e:
            return ToolResult(error=f"API Request failed: {e}")
        except Exception as e:
            return ToolResult(error=f"Unexpected error: {e}")
