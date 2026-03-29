"""Glob and grep tools for searching files with workspace confinement."""

import logging
import re
from pathlib import Path

from pydantic import BaseModel

from ..safety import SafetyConfig, SecurityValidator
from . import Tool, ToolResult

logger = logging.getLogger(__name__)


DANGEROUS_REGEX_PATTERNS = [
    r"\(.*\)\{",  # Nested groups with quantifiers
    r"\{.*\}\+",  # Quantifiers without bounds
    r"\.\*\{",  # Greedy quantifiers
    r"\(\?\!",  # Negative lookahead
    r"\(\?<=",  # Negative lookbehind
    r"\(\?\<",  # Named groups with quantifiers
]


def sanitize_search_query(query: str) -> str:
    """Sanitize search query to prevent XSS and injection attacks."""
    if not query:
        return ""

    original_query = query
    dangerous = [
        "<script",
        "javascript:",
        "data:",
        "onerror=",
        "onclick=",
        "onload=",
        "onmouseover=",
        "expression(",
        "url(",
    ]
    for pattern in dangerous:
        if pattern in query:
            logger.debug("Sanitized dangerous pattern '%s' from search query", pattern)
            query = query.replace(pattern, "")

    result = query.strip()[:500]
    if len(result) < len(original_query):
        logger.debug(
            "Search query truncated from %d to %d chars",
            len(original_query),
            len(result),
        )
    return result


def sanitize_glob_pattern(pattern: str) -> str:
    """Sanitize glob pattern to prevent path traversal."""
    if not pattern:
        return ""

    original_len = len(pattern)
    pattern = pattern.strip()

    dangerous = ["..", "~", "$", "`", "|", ";", "&", "\n", "\r", "\0"]
    for char in dangerous:
        if char in pattern:
            logger.debug("Removed dangerous character '%s' from glob pattern", char)
            pattern = pattern.replace(char, "")

    if len(pattern) > 500:
        logger.debug("Glob pattern truncated from %d to 500 chars", len(pattern))
        pattern = pattern[:500]
    elif len(pattern) < original_len:
        logger.debug(
            "Glob pattern sanitized from %d to %d chars", original_len, len(pattern)
        )

    return pattern


def validate_regex_pattern(pattern: str) -> tuple[bool, str]:
    """Validate regex pattern for safety (ReDoS prevention).

    Returns:
        Tuple of (is_safe, error_message)
    """
    if not pattern:
        return False, "Empty pattern"

    if len(pattern) > 200:
        return False, "Pattern too long"

    for dangerous in DANGEROUS_REGEX_PATTERNS:
        if re.search(dangerous, pattern):
            return False, "Dangerous regex pattern detected"

    try:
        re.compile(pattern)
    except re.error as e:
        return False, f"Invalid regex: {e}"

    return True, ""


class GlobParams(BaseModel):
    """Parameters for GlobTool."""

    pattern: str


class GrepParams(BaseModel):
    """Parameters for GrepTool."""

    pattern: str
    path: str = "."


class GlobTool(Tool):
    """Find files by pattern with workspace confinement."""

    parameters_model = GlobParams

    def __init__(self, base_dir: str = ".", safety_config: SafetyConfig | None = None):
        super().__init__(
            name="glob",
            description="Find files matching a glob pattern.",
        )
        self.base_dir = Path(base_dir).resolve()

        if safety_config:
            safety_config.workspace = str(self.base_dir)
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(
                SafetyConfig(workspace=str(self.base_dir))
            )

    async def execute(self, pattern: str, **kwargs) -> ToolResult:
        """Find matching files with safety checks."""
        pattern = sanitize_glob_pattern(pattern)

        if not pattern:
            return ToolResult(error="Invalid or empty pattern")

        if self.validator.is_blocked_extension(pattern):
            return ToolResult(error="Cannot search for blocked extension")

        if not self.validator.check_path_traversal(pattern):
            return ToolResult(error="Path traversal blocked")

        try:
            matches = list(self.base_dir.glob(pattern))
            matches = [
                m for m in matches if self.validator.check_path_traversal(str(m))
            ]

            if not matches:
                return ToolResult(content=f"No files matching '{pattern}'")

            max_results = getattr(self, "max_glob_results", 100)
            result = "\n".join(
                str(m.relative_to(self.base_dir)) for m in sorted(matches)[:max_results]
            )
            return ToolResult(content=result)
        except Exception as e:
            return ToolResult(error=str(e))


class GrepTool(Tool):
    """Search file contents with workspace confinement."""

    parameters_model = GrepParams

    def __init__(
        self,
        base_dir: str = ".",
        safety_config: SafetyConfig | None = None,
        max_glob_results: int = 100,
        max_grep_results: int = 100,
    ):
        super().__init__(
            name="grep",
            description="Search for a pattern in files.",
        )
        self.base_dir = Path(base_dir).resolve()
        self.max_glob_results = max_glob_results
        self.max_grep_results = max_grep_results

        if safety_config:
            safety_config.workspace = str(self.base_dir)
            self.validator = SecurityValidator(safety_config)
        else:
            self.validator = SecurityValidator(
                SafetyConfig(workspace=str(self.base_dir))
            )

    async def execute(self, pattern: str, path: str = ".", **kwargs) -> ToolResult:
        """Search for pattern in files with safety checks."""
        pattern = sanitize_search_query(pattern)

        if not pattern:
            return ToolResult(error="Invalid or empty pattern")

        is_safe, error = validate_regex_pattern(pattern)
        if not is_safe:
            return ToolResult(error=f"Invalid pattern: {error}")

        if not self.validator.check_path_traversal(path):
            return ToolResult(error="Path traversal blocked")

        try:
            search_path = (self.base_dir / path).resolve()
            if not search_path.exists():
                return ToolResult(error=f"Path not found: {path}")

            regex = re.compile(pattern)
            results = []

            if search_path.is_file():
                files = [search_path]
            else:
                files = list(search_path.rglob("*"))
                files = [
                    f
                    for f in files
                    if f.is_file() and self.validator.check_path_traversal(str(f))
                ]

            for f in files:
                if self.validator.is_blocked_extension(str(f)):
                    continue
                try:
                    for i, line in enumerate(f.read_text().splitlines(), 1):
                        if regex.search(line):
                            results.append(
                                f"{f.relative_to(self.base_dir)}:{i}: {line}"
                            )
                            if len(results) >= self.max_grep_results:
                                break
                except (OSError, UnicodeDecodeError):
                    continue

            if not results:
                return ToolResult(content=f"No matches for '{pattern}'")

            return ToolResult(content="\n".join(results))
        except Exception as e:
            return ToolResult(error=str(e))
