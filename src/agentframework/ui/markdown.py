"""Markdown rendering utilities for FastHTML UI."""

from markdown import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer, ClassNotFound
from pygments.formatters import HtmlFormatter


def render_code(code: str, language: str = "") -> str:
    """Render code with syntax highlighting."""
    try:
        if language:
            lexer = get_lexer_by_name(language)
        else:
            lexer = guess_lexer(code)
    except ClassNotFound:
        lexer = get_lexer_by_name("text")

    formatter = HtmlFormatter(nowrap=True, cssclass="codehilite")
    return highlight(code, lexer, formatter)


def render_markdown(text: str) -> str:
    """Render markdown text to HTML with code highlighting."""
    import re

    code_block_pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

    def replace_code_block(match):
        language = match.group(1) or ""
        code = match.group(2)
        return f"\n{render_code(code, language)}\n"

    text = code_block_pattern.sub(replace_code_block, text)

    html = markdown(text, extensions=["fenced_code", "tables", "nl2br"])

    return html


def format_message_content(content: str) -> str:
    """Format message content for display - handles markdown and plain text."""
    if not content:
        return ""

    if any(char in content for char in ["*", "`", "#", "-", ">", "[", "."]):
        return render_markdown(content)

    return content
