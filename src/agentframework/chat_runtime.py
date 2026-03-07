"""Runtime helpers for chat loop operations."""

import asyncio
import re

import aiohttp
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter

from .chat_commands import all_slash_commands

command_completer = WordCompleter(
    all_slash_commands(),
    ignore_case=True,
    pattern=re.compile(r"[\w/]+"),
)
prompt_session = PromptSession(completer=command_completer)


async def get_input(prompt_text: str = "\n> ") -> str:
    """Get user input with autocomplete support (async)."""
    try:
        return await prompt_session.prompt_async(prompt_text)
    except Exception:
        return await asyncio.to_thread(input, prompt_text)


def current_query_tool_messages(messages: list, tool_names: set[str] | None = None) -> list:
    """Return tool messages associated with the current user query."""
    user_indexes = [i for i, message in enumerate(messages) if message.role == "user"]

    if len(user_indexes) >= 2:
        candidates = messages[user_indexes[-2] + 1 : user_indexes[-1]]
    elif len(user_indexes) == 1:
        candidates = messages
    else:
        candidates = []

    if tool_names is None:
        return [m for m in candidates if m.role == "tool"]
    return [m for m in candidates if m.role == "tool" and m.tool_name in tool_names]


def extract_urls(clean_response: str, tool_messages: list) -> list[tuple[str, str]]:
    """Extract and deduplicate candidate sources from response and tool outputs."""
    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", clean_response)
    url_only = re.findall(r"\((https?://[^)]+)\)", clean_response)

    tool_urls: set[str] = set()
    for message in tool_messages:
        found = re.findall(r'(https?://[^\s\)"\']+)', message.content or "")
        tool_urls.update(found)

    all_urls = list(links)
    seen_urls = {pair[1] for pair in links}

    for url in url_only:
        if url not in seen_urls:
            all_urls.append((url, url))
            seen_urls.add(url)

    for url in tool_urls:
        if url not in seen_urls:
            name = url.split("/")[2] if len(url.split("/")) > 2 else url
            all_urls.append((name, url))
            seen_urls.add(url)

    return all_urls


async def fetch_titles(url_pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Fetch HTML titles for a list of URLs."""
    titles: dict[str, str] = {}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
        for _, url in url_pairs:
            try:
                async with session.get(url, ssl=False) as response:
                    if response.status != 200:
                        continue
                    html = await response.text()
                    match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
                    if match:
                        titles[url] = match.group(1).strip()[:60]
            except Exception:
                continue  # nosec B112
    return titles
