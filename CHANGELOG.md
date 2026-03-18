# Changelog

All notable changes to this project should be documented in this file.

The format is inspired by [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project follows semantic versioning where practical.

## [Unreleased]

### Added
- Web UI streaming metrics (TTFB, Total time).
- Sources dropdown for web search results in the UI.
- Collapsible thought process display for thinking models.
- Mobile-responsive sidebar and layout for web interface.
- Session management API: rename and purge capabilities.
- Multi-window support for simultaneous Chat and Workflow views.
- Automatic session titling using the LLM.

### Changed
- WebSocket robustness: added buffering during connection startup and improved reconnection logic.
- UI message filtering: refined to better handle assistant tool calls and internal framework logs.
- Document review system: exposed recommendations for UI hints.

### Fixed
- SQLite database ResourceWarnings by correctly closing connections in SessionManager and VectorStore.
- Security vulnerabilities identified by pip-audit and bandit (dependency upgrades and static analysis findings).
- Repository lint errors and path corruption issues in utility scripts.
- Web search helper type hints and dependency setup consistency.
- Benchmark script crashes.

## Release process notes

- Update this file as part of every merge that changes behavior.
- Keep entries concise and user-visible.
- Group changes under Added/Changed/Fixed whenever possible.
