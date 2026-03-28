"""Markdown rendering with syntax highlighting for NiceGUI."""

import re
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter

CODE_BLOCK_PATTERN = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def render_markdown(text: str) -> str:
    """Render markdown text with syntax highlighting."""
    if not text:
        return ""

    def replace_code(match):
        lang = match.group(1) or "text"
        code = match.group(2)

        try:
            lexer = get_lexer_by_name(lang)
        except Exception:
            lexer = guess_lexer(code) if code else None

        if lexer:
            highlighted = highlight(code, lexer, HtmlFormatter())
            return f'<div class="code-block">{highlighted}</div>'
        return f"<pre><code>{code}</code></pre>"

    text = CODE_BLOCK_PATTERN.sub(replace_code, text)

    html = markdown.markdown(
        text,
        extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    )

    return html
