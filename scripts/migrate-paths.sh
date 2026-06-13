#!/usr/bin/env bash
set -euo pipefail

ECHO_AI="${HOME}/.echo-ai"
PROJECT_DIR="${HOME}/echo-ai"
DRY_RUN="${DRY_RUN:-}"

migrate() {
    local src="$1" dst="$2" label="$3"
    if [ -e "$src" ]; then
        if [ -n "$DRY_RUN" ]; then
            printf "  WOULD COPY: %s\n    → %s\n" "$src" "$dst"
        else
            mkdir -p "$(dirname "$dst")"
            cp -a "$src" "$dst"
            printf "  ✓ %s\n    %s → %s\n" "$label" "$src" "$dst"
        fi
    else
        printf "  - %s: source not found (%s)\n" "$label" "$src"
    fi
}

echo "=== Echo AI Path Migration ==="
printf "New base directory: %s\n\n" "$ECHO_AI"
[ -n "$DRY_RUN" ] && echo "  [DRY RUN - no files will be copied]"
echo ""

mkdir -p "$ECHO_AI"

# 1. Memory database
migrate \
    "${HOME}/.agent_memory/memory.db" \
    "${ECHO_AI}/memory/memory.db" \
    "Memory DB"

# 2. Personal notes
migrate \
    "${HOME}/personal_notes" \
    "${ECHO_AI}/notes" \
    "Notes directory"

# 3. Session database + backups
if [ -d "${PROJECT_DIR}/.agent_sessions" ]; then
    migrate \
        "${PROJECT_DIR}/.agent_sessions/agent_sessions.db" \
        "${ECHO_AI}/sessions/agent_sessions.db" \
        "Session DB"
    if [ -d "${PROJECT_DIR}/.agent_sessions/.backups" ]; then
        migrate \
            "${PROJECT_DIR}/.agent_sessions/.backups" \
            "${ECHO_AI}/sessions/.backups" \
            "Session backups"
    fi
else
    printf "  - Session DB: source not found (%s)\n" "${PROJECT_DIR}/.agent_sessions"
fi

# 4. Environment file
migrate \
    "${HOME}/.config/agentframework/.env" \
    "${ECHO_AI}/.env" \
    "Environment file"

# 5. Config file (project-level → user-level)
migrate \
    "${PROJECT_DIR}/config.yaml" \
    "${ECHO_AI}/config.yaml" \
    "Config file"

echo ""
if [ -z "$DRY_RUN" ]; then
    echo "=== Migration complete. Old paths are preserved. ==="
    echo "You can remove old directories after verifying:"
    echo "  rm -rf ~/.agent_memory"
    echo "  rm -rf ~/personal_notes"
    echo "  rm -rf ~/.config/agentframework"
    echo "  rm -rf ${PROJECT_DIR}/.agent_sessions"
    echo ""
    echo "The project-local config.yaml at ${PROJECT_DIR}/config.yaml"
    echo "is now shadowed by ${ECHO_AI}/config.yaml — you may want to"
    echo "remove the project-local copy to avoid confusion."
else
    echo "=== Dry run complete. Nothing was changed. ==="
    echo "Re-run without DRY_RUN=1 to execute."
fi
