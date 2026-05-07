#!/usr/bin/env bash
# One-shot installer for the Proton Bridge MCP server.
# Creates a venv next to this script and installs mcp + pydantic into it.

set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first (e.g. from python.org or Homebrew)." >&2
  exit 1
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip

# Install hash-pinned dependencies. --require-hashes ensures every package and
# every transitive dep matches a known-good hash; if PyPI ever serves a tampered
# wheel, install fails loudly instead of silently picking it up.
pip install --require-hashes -r requirements.txt

echo
echo "Done. Next:"
echo "  1. Run ./setup_keychain.sh you@example.com to store your Bridge app-password."
echo "  2. Merge claude_desktop_config.example.json into"
echo "     ~/Library/Application Support/Claude/claude_desktop_config.json"
echo "  3. Quit Claude (⌘Q) and relaunch."
