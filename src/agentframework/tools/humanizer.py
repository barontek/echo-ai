"""Humanizer tool - removes AI writing patterns from text."""

from pathlib import Path

from pydantic import BaseModel

from ..constants import DEFAULT_MODEL
from . import Tool, ToolResult

_HUMANIZER_INSTRUCTIONS_PATH = Path(__file__).parent / "prompts" / "humanizer_instructions.txt"


def _load_humanizer_instructions() -> str:
    """Load humanizer instructions from prompts file."""
    try:
        return _HUMANIZER_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "You are a writing editor that removes signs of AI-generated text."


class HumanizerParams(BaseModel):
    """Parameters for HumanizerTool."""

    text: str
    voice_sample: str = ""


class HumanizerTool(Tool):
    """Tool that removes AI writing patterns from text."""

    parameters_model = HumanizerParams

    def __init__(self, llm_provider=None):
        super().__init__(
            name="humanizer",
            description="Remove signs of AI-generated writing from text, making it sound more natural and human. Detects and fixes 33+ patterns including inflated symbolism, promotional language, em dash overuse, rule of three, AI vocabulary words, and filler phrases.",
        )
        self._llm = llm_provider

    def _get_provider(self):
        if self._llm is None:
            from ..providers import get_provider
            from ..config import load_config
            config = load_config()
            model_cfg = config.get("model", {})
            self._llm = get_provider(
                name=model_cfg.get("provider", "ollama"),
                model=model_cfg.get("name") or DEFAULT_MODEL,
                base_url=model_cfg.get("base_url"),
                timeout=model_cfg.get("timeout", 300),
                num_ctx=model_cfg.get("num_ctx"),
            )
        return self._llm

    async def execute(
        self, text: str, voice_sample: str = "", **kwargs
    ) -> ToolResult:
        system_prompt = _load_humanizer_instructions()
        if voice_sample:
            system_prompt += (
                f"\n\n## Voice Calibration\n"
                f"Here is a sample of the author's writing to match their style:\n"
                f"{voice_sample}\n\n"
                f"Match the sentence length patterns, word choice level, "
                f"punctuation habits, and overall voice from this sample."
            )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Humanize this text:\n\n{text}"},
        ]

        try:
            response = await self._get_provider().chat(
                messages=messages,
                temperature=0.3,
            )
            result = response.content.strip()
            if not result:
                return ToolResult(error="Humanizer returned empty result")
            # Provider errors get returned as tool errors, not as humanized content
            if any(
                result.startswith(prefix)
                for prefix in (
                    "HTTP error:",
                    "An internal error occurred",
                    "LM Studio error:",
                    "Anthropic error:",
                    "OpenAI error:",
                )
            ):
                return ToolResult(error=result)
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(error=f"Humanizer failed: {str(e) or type(e).__name__}")
