#!/usr/bin/env bash
# Store the Proton Bridge app-password in the macOS Keychain.
# Run this ONCE after installing. You can rotate later by re-running.
#
# Usage:  ./setup_keychain.sh your-email@domain.tld

set -euo pipefail

SERVICE="${PROTON_BRIDGE_KEYCHAIN_SVC:-proton_bridge_mcp}"
ACCOUNT="${1:-}"

if [[ -z "$ACCOUNT" ]]; then
  echo "Usage: $0 <bridge-username-usually-your-email>" >&2
  exit 2
fi

read -r -s -p "Paste your Proton Bridge app-password (input hidden): " PW
echo

if [[ -z "$PW" ]]; then
  echo "No password entered — aborting." >&2
  exit 2
fi

# NOTE: -T /usr/bin/security explicitly trusts the macOS `security` CLI as a
# reader of this keychain item. The Python MCP shells out to /usr/bin/security
# to fetch the password at runtime; without this ACL macOS will prompt on every
# spawn of the MCP process and "Always Allow" will not persist across restarts.
/usr/bin/security add-generic-password \
  -U \
  -s "$SERVICE" \
  -a "$ACCOUNT" \
  -T /usr/bin/security \
  -w "$PW"

echo
echo "Stored in Keychain:"
echo "  service: $SERVICE"
echo "  account: $ACCOUNT"
echo
echo "Verify with:"
echo "  security find-generic-password -s $SERVICE -a $ACCOUNT -g"
