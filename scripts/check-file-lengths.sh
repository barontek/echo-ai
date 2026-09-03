#!/usr/bin/env bash
# check-file-lengths.sh - file-size audit for the 300-800 comfortable /
# 1000+ split signal from AGENTS.md "Code style — File size". Non-blocking
# report; a file over 1000 lines is a candidate to split, not an error.
set -eu

root="$(cd "$(dirname "$0")/.." && pwd)"
max=0
while IFS= read -r -d '' f; do
    lines=$(wc -l < "$f")
    if [ "$lines" -gt 800 ]; then
        printf '%5d  %s\n' "$lines" "${f#"$root"/}"
    fi
    [ "$lines" -gt "$max" ] && max="$lines"
done < <(find "$root/crates" -name '*.rs' -print0)

echo "---"
echo "largest .rs file: $max lines (target band: 300-800)"