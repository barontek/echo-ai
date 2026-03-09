"""Security and safety measures for the agent framework."""

import fnmatch
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


DANGEROUS_PATTERNS = [
    (re.compile(r'rm\s+-rf\s+/'), "Recursive deletion of root"),
    (re.compile(r'rm\s+-rf\s+'), "Recursive deletion"),
    (re.compile(r'dd\s+if='), "Direct device read"),
    (re.compile(r':\(\)\{'), "Fork bomb"),
    (re.compile(r'curl.*\|\s*(sh|bash|zsh)'), "Download and execute"),
    (re.compile(r'wget.*\|\s*(sh|bash|zsh)'), "Download and execute"),
    (re.compile(r'python.*-c.*exec'), "Python code execution"),
    (re.compile(r'perl.*-e.*'), "Perl code execution"),
    (re.compile(r'ruby.*-e.*'), "Ruby code execution"),
    (re.compile(r'node.*-e.*'), "Node.js code execution"),
    (re.compile(r'>\s*/dev/sd'), "Direct disk write"),
    (re.compile(r'mkfs\.'), "Filesystem creation"),
    (re.compile(r'mount\s+--bind'), "Bind mount"),
    (re.compile(r'chmod\s+[47]777'), "Overly permissive permissions"),
    (re.compile(r'chown\s+-R'), "Recursive ownership change"),
    (re.compile(r'sudo\s+rm'), "sudo delete"),
    (re.compile(r'sudo\s+rm\s+-rf'), "sudo recursive delete"),
    (re.compile(r'sudo\s+rm\s+/'), "sudo delete root"),
    (re.compile(r'>\s*/etc/passwd'), "Write to passwd"),
    (re.compile(r'>\s*/etc/shadow'), "Write to shadow"),
    (re.compile(r'git\s+push\s+--force'), "Force push"),
    (re.compile(r'docker\s+run\s+--rm\s+-v\s+/'), "Docker volume mount"),
    (re.compile(r'nc\s+-e\s+'), "Netcat reverse shell"),
    (re.compile(r'/bin/(sh|bash)\s+-i'), "Interactive shell"),
    (re.compile(r'eval\s+'), "Eval execution"),
    (re.compile(r'exec\s+'), "Exec execution"),
]

DESTRUCTIVE_KEYWORDS = [
    'delete', 'destroy', 'remove', 'drop', 'truncate', 'erase',
    'rm -rf', 'rmdir', 'unlink', 'deltree',
    'format', 'fdisk', 'mkfs',
    '--force', '-f', '--force', 'force',
    'chmod 777', 'chmod -r', 'chown -r',
]

SAFE_COMMANDS = {
    'git': ['status', 'diff', 'log', 'show', 'branch', 'fetch', 'clone', 'init'],
    'npm': ['install', 'run', 'test', 'build', 'start', 'dev'],
    'pip': ['install', 'list', 'show', 'freeze'],
    'cargo': ['build', 'test', 'run', 'check', 'clippy'],
    'make': [],
    'ls': [],
    'cat': [],
    'grep': [],
    'find': [],
    'echo': [],
    'pwd': [],
    'cd': [],
}

BLOCKED_EXTENSIONS = [
    '*.key', '*.pem', '*.pub', '*.secret', '*.token',
    '*.env', '*.password', '*.credential', '*.api_key',
    '*.aws', '*.gcp', '*.azure', 'id_rsa', 'id_ed25519',
    '.git/credentials', '.netrc', '.htpasswd',
]

BLOCKED_PATHS = [
    '/etc/passwd', '/etc/shadow', '/etc/sudoers',
    '/root', '/home/*/.ssh', '/home/*/.aws',
    '*/.git/config', '*.env', '.env.*',
]


@dataclass
class SafetyConfig:
    """Safety configuration for the agent."""

    workspace: str = "."
    allowed_commands: list[str] = field(default_factory=lambda: ["*"])
    blocked_commands: list[str] = field(default_factory=list)
    allow_network: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    max_file_size: int = 10 * 1024 * 1024
    max_execution_time: int = 60
    require_approval_for: list[str] = field(default_factory=lambda: ["bash", "write_file", "memory"])
    approval_callback: Optional[Callable[[str, str], bool]] = None
    audit_log_path: Optional[str] = None
    read_requires_approval: bool = False
    read_size_threshold: int = 100 * 1024


class SecurityValidator:
    """Validates operations against security policies."""

    def __init__(self, config: SafetyConfig):
        self.config = config
        self.workspace_path = Path(config.workspace).resolve()
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns for efficiency."""
        self._dangerous_patterns = DANGEROUS_PATTERNS
        self._blocked_extensions = [re.compile(fnmatch.translate(p)) for p in BLOCKED_EXTENSIONS]
        self._blocked_path_patterns = [re.compile(fnmatch.translate(p)) for p in BLOCKED_PATHS]

    def check_path_traversal(self, path: str) -> bool:
        """Check for path traversal attempts."""
        try:
            resolved = (self.workspace_path / path).resolve()
            return resolved.is_relative_to(self.workspace_path)
        except Exception:
            return False

    def is_blocked_extension(self, path: str) -> bool:
        """Check if file has blocked extension."""
        filename = os.path.basename(path)
        for pattern in self._blocked_extensions:
            if pattern.match(filename):
                return True
        return False

    def is_blocked_path(self, path: str) -> bool:
        """Check if path is in blocked list."""
        for pattern in self._blocked_path_patterns:
            if pattern.match(path):
                return True
        return False

    def check_command_safety(self, command: str) -> tuple[bool, str]:
        """Check if command is safe to execute natively, parsing shell control logic via shlex."""
        cmd_lower = command.lower().strip()
        
        # We always check raw command strings against Regex dangerous patterns immediately
        # (Since some operators like `:(){` or basic `sudo rm -rf` might span tokens weirdly).
        for pattern, reason in self._dangerous_patterns:
            if pattern.search(command):
                return False, f"Dangerous pattern detected: {reason}"

        import shlex
        import re

        try:
            # We must break the string across bash boundary chaining loops to inspect them individually
            # Because `shlex` doesn't natively treat `;` or `&&` as command splitters dynamically unless explicitly instructed.
            sub_commands = re.split(r'(?:;|&&|\|\||\|)', cmd_lower)
            
            for sub_cmd in sub_commands:
                sub_cmd = sub_cmd.strip()
                if not sub_cmd:
                    continue
                    
                parts = shlex.split(sub_cmd)
                if not parts:
                    continue
                
                # Check for explicit bash variable assignments directly (e.g. "X=/; rm -rf $X")
                # Shlex handles "X=/" as a single token but assigning it dynamically hides logic.
                # If a part contains typical assignment operators out of band, flag immediately
                # Example: `parts = ['X=/', 'rm', '-rf', '$X']`.
                # We need to evaluate the execution block. The base command here is usually the first non-variable token.
                # To be rigorous, we strip out leading variable assignments from the 'base_cmd' inspection natively.
                executable_parts = []
                for p in parts:
                    if "=" not in p or p.startswith("-"): # Quick heuristic to skip env vars preceding a command (e.g. `DEBUG=1 npm start`)
                        executable_parts.append(p)
                        
                if not executable_parts:
                    continue # It was purely an assignment
                    
                base_cmd = executable_parts[0]

                # Check blocked commands - compile regex patterns natively
                if self.config.blocked_commands:
                    for blocked in self.config.blocked_commands:
                        if not isinstance(blocked, str):
                            continue
                        try:
                            if re.search(blocked, base_cmd):
                                return False, f"Command '{base_cmd}' is blocked"
                        except re.error:
                            # Fall back to fnmatch for simple patterns
                            if fnmatch.fnmatch(base_cmd, blocked):
                                return False, f"Command '{base_cmd}' is blocked"

                # Check allowed commands
                allowed = self.config.allowed_commands
                if allowed and "*" not in allowed:
                    allowed_found = False
                    for pattern in allowed:
                        if isinstance(pattern, str) and fnmatch.fnmatch(base_cmd, pattern):
                            allowed_found = True
                            break
                    if not allowed_found:
                        return False, f"Command '{base_cmd}' not in allowlist"

                if base_cmd in SAFE_COMMANDS:
                    allowed_args = SAFE_COMMANDS[base_cmd]
                    if allowed_args and len(executable_parts) > 1:
                        subcmd = executable_parts[1]
                        if subcmd not in allowed_args and '*' not in allowed_args:
                            return False, f"Subcommand '{subcmd}' not allowed for {base_cmd}"
                            
        except ValueError as e:
            return False, f"Malformed command string: {e}"

        return True, "OK"

    def check_network_allowed(self, url: str) -> tuple[bool, str]:
        """Check if network request is allowed."""
        if self.config.allow_network:
            if not self.config.allowed_domains:
                return True, "OK"
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            for allowed in self.config.allowed_domains:
                # Remove wildcard prefix for subdomain matching
                pattern = allowed.lstrip("*.")
                if fnmatch.fnmatch(domain, allowed) or domain == pattern or domain.endswith("." + pattern):
                    return True, "OK"
            return False, f"Domain not in allowlist: {domain}"
        return False, "Network access disabled"

    def check_file_size(self, content: str | None = None, path: str | None = None) -> bool:
        """Check if file size is within limits."""
        if content and len(content.encode()) > self.config.max_file_size:
            return False
        if path:
            try:
                size = Path(path).stat().st_size
                return size <= self.config.max_file_size
            except OSError:
                pass
        return True

    def requires_approval(self, tool_name: str, path: str | None = None, content: str | None = None) -> bool:
        """Check if tool requires user approval."""
        if tool_name in self.config.require_approval_for:
            return True

        if tool_name == "read_file":
            if self.config.read_requires_approval:
                return True
            if path:
                try:
                    file_path = Path(path)
                    if file_path.exists():
                        size = file_path.stat().st_size
                        if size > self.config.read_size_threshold:
                            return True
                except OSError:
                    pass

        return False

    def check_destructive_keywords(self, command: str) -> list[str]:
        """Check for destructive keywords in command."""
        found = []
        cmd_lower = command.lower()
        for keyword in DESTRUCTIVE_KEYWORDS:
            if keyword in cmd_lower:
                found.append(keyword)
        return found

    def log_approval(self, tool_name: str, details: str, approved: bool):
        """Log approval/denial to audit file."""
        if not self.config.audit_log_path:
            return

        try:
            timestamp = datetime.now().isoformat()
            status = "APPROVED" if approved else "DENIED"
            log_entry = f"[{timestamp}] {status}: {tool_name} - {details}\n"

            audit_path = Path(self.config.audit_log_path)
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(audit_path, "a") as f:
                f.write(log_entry)
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")

    def get_approval(self, tool_name: str, details: str) -> bool:
        """Get user approval for dangerous operation."""
        if not self.requires_approval(tool_name):
            return True

        if self.config.approval_callback:
            approved = self.config.approval_callback(tool_name, details)
            self.log_approval(tool_name, details, approved)
            return approved

        logger.warning(f"Approval required for {tool_name}: {details}")
        self.log_approval(tool_name, details, False)
        return False


def create_safety_validator(config: SafetyConfig | None = None) -> SecurityValidator:
    """Create a security validator with default or custom config."""
    if config is None:
        config = SafetyConfig()
    return SecurityValidator(config)
