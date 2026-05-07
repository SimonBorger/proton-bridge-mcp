# proton-bridge-mcp

A local Model Context Protocol (MCP) server that lets Claude (or any MCP client) read, search, draft, send, and organise email through your running **Proton Mail Bridge**. Everything stays on your Mac — Claude talks to Bridge over `127.0.0.1` IMAP (1143) and SMTP (1025). Nothing transits the public internet via this server.

## Why this exists

Proton Mail's end-to-end encryption is great for privacy and a problem for automation: there's no public IMAP endpoint and no first-party API. **Proton Mail Bridge** solves that by exposing your decrypted mail over loopback IMAP/SMTP on your own machine. This MCP server wraps that loopback in a small, hardened tool surface that Claude can drive.

## Tool surface

| Tool                         | Purpose                                                  | Annotations     |
| ---------------------------- | -------------------------------------------------------- | --------------- |
| `proton_list_folders`        | List every mailbox / label                               | read-only       |
| `proton_list_recent`         | N newest messages in a mailbox (headers only)            | read-only       |
| `proton_search_emails`       | IMAP SEARCH (from / to / subject / body / date / flags)  | read-only       |
| `proton_read_email`          | Full headers + text + (optional) HTML + attachments list | read-only       |
| `proton_download_attachment` | Save a specific attachment to disk                       | read-only (I/O) |
| `proton_flag_email`          | Mark read/unread, flag/unflag                            | mutate          |
| `proton_move_email`          | Move a message to another mailbox                        | mutate          |
| `proton_delete_email`        | Move to Trash (or permanently expunge)                   | destructive     |
| `proton_send_email`          | Send via Bridge SMTP, optional append-to-Sent            | mutate          |
| `proton_create_draft`        | Save a draft in Drafts for manual review                 | mutate          |

## Hardening highlights

- **Credentials in the macOS Keychain**, never in `claude_desktop_config.json`. The config file only names the Keychain service and account.
- **TLS pinning** against Bridge's own self-signed certificate, captured on first run via STARTTLS. Set `PROTON_BRIDGE_TLS_POLICY=pinned` to fail hard if the cert can't be located.
- **Pooled connections**: one long-lived IMAP session and one SMTP session per process, guarded by asyncio locks, with auto-reconnect on drops. No per-call login storms.
- **Non-blocking**: blocking stdlib IMAP/SMTP calls run in `asyncio.to_thread` so the event loop stays responsive.
- **Hash-pinned dependencies** (`requirements.txt`) so the install is reproducible and supply-chain attacks are caught at install time.
- **Reads never implicitly mark messages read** — `mark_seen=false` is the default on `proton_read_email`.

## Prerequisites

- macOS (Keychain integration is macOS-specific)
- Proton Mail Bridge installed, running, and logged in
- Python 3.10 or later (tested on 3.10, 3.12, and 3.14)
- Bridge **username** (your email) and **app-password**, copied from Bridge → *Mailbox details*. This is **not** your Proton account password.

## Install

There are two paths. Use **A** unless you want fine control over each step.

### A. One-shot bootstrap

```bash
cd <install-path>/proton-bridge-mcp
/usr/bin/python3 bootstrap.py
```

`bootstrap.py` is idempotent and re-runnable. It:

1. Creates `.venv` next to the script.
2. Installs the hash-pinned dependencies from `requirements.txt`.
3. Captures Bridge's TLS certificate via STARTTLS (trust-on-first-use) and saves it to `~/.config/proton-bridge-mcp/cert.pem` with `0600` perms.
4. Prompts once for your Bridge app-password and writes it to the macOS Keychain under service `proton_bridge_mcp`, account = your username, with `/usr/bin/security` on the trusted-applications list (so macOS does not prompt again on every MCP process spawn).
5. Verifies IMAP login end-to-end with the pinned cert.
6. Merges a `proton_bridge` block into `~/Library/Application Support/Claude/claude_desktop_config.json`, preserving any other MCP servers you have configured.

Then **fully quit Claude Desktop (⌘Q) and relaunch**.

### B. Manual three-step install

```bash
cd <install-path>/proton-bridge-mcp

# 1. Create the venv and install hash-pinned dependencies
./install.sh

# 2. Put the Bridge app-password in the macOS Keychain
./setup_keychain.sh you@example.com
# (prompts for the password — paste it; nothing is echoed)

# 3. Merge the entry from claude_desktop_config.example.json into
#    ~/Library/Application Support/Claude/claude_desktop_config.json
#    (no password goes in this file — the Keychain handles that).
```

Then quit and relaunch Claude Desktop.

## Verifying

In a new conversation, ask Claude:

> Using proton_bridge, list my mail folders.

Then something with bite:

> Search proton_bridge for all mail to or from `@example.com` in the last 12 months, in any folder. Read the most recent 10 threads.

## Configuration reference

All configuration is done via the `env` block in `claude_desktop_config.json`. See `claude_desktop_config.example.json` for a starting template.

| Variable                          | Required | Default       | Notes                                                                                  |
| --------------------------------- | -------- | ------------- | -------------------------------------------------------------------------------------- |
| `PROTON_BRIDGE_USER`              | yes      | —             | Your Bridge username (usually your email).                                             |
| `PROTON_BRIDGE_HOST`              | no       | `127.0.0.1`   | Bridge listens on loopback by default — leave alone unless you know why.               |
| `PROTON_BRIDGE_IMAP_PORT`         | no       | `1143`        | Per Bridge → *Advanced settings*.                                                      |
| `PROTON_BRIDGE_SMTP_PORT`         | no       | `1025`        | Per Bridge → *Advanced settings*.                                                      |
| `PROTON_BRIDGE_DEFAULT_FROM`      | no       | = `_USER`     | Used when sending if `from_addr` isn't specified per call.                             |
| `PROTON_BRIDGE_CERT_PATH`         | no       | autoresolve   | Path to Bridge's TLS cert. The bootstrap captures it; otherwise `_locate_bridge_cert` searches well-known locations. |
| `PROTON_BRIDGE_TLS_POLICY`        | no       | `best_effort` | `best_effort` falls back to `CERT_NONE` on loopback if cert can't be read; `pinned` fails hard. |
| `PROTON_BRIDGE_KEYCHAIN_SVC`      | no       | `proton_bridge_mcp` | Keychain service name. Override only if you have multiple Bridge accounts.       |
| `PROTON_BRIDGE_PASS`              | no       | —             | Direct password fallback. Avoid; prefer Keychain. Useful for headless / CI.            |
| `PROTON_BRIDGE_LOG_LEVEL`         | no       | `INFO`        | Standard Python log level.                                                             |

## Rotating and revoking

- **Rotate the Bridge app-password**: regenerate in Bridge → *Mailbox details*, then re-run `./setup_keychain.sh you@example.com` (or `bootstrap.py --force-password`).
- **Delete the Keychain entry**: `security delete-generic-password -s proton_bridge_mcp -a you@example.com`.
- **Remove entirely**: delete the `proton_bridge` block from `claude_desktop_config.json`, then delete this folder.

## Troubleshooting

| Symptom                                                                                    | Fix                                                                                                                                                                                                                                                                                                                                                                                              |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `credentials: Proton Bridge password not found`                                            | Run `./setup_keychain.sh you@example.com`, or set `PROTON_BRIDGE_PASS` env var as a temporary fallback. If the password used to load and stopped, see "macOS prompts for Keychain access on every restart" below.                                                                                                                                                                                |
| **macOS prompts for Keychain access on every restart**, even after clicking "Always Allow" | The Keychain item is missing `/usr/bin/security` on its trusted-applications ACL. Re-add the entry with `security add-generic-password -U -s proton_bridge_mcp -a you@example.com -T /usr/bin/security -w '<bridge-app-password>'`. The `bootstrap.py` and updated `setup_keychain.sh` in this repo do this correctly. Older deployments may need this manual fix.                              |
| `tls: Bridge cert not found; falling back to CERT_NONE`                                    | Set `PROTON_BRIDGE_CERT_PATH` to the real Bridge cert location (the bootstrap script saves it to `~/.config/proton-bridge-mcp/cert.pem`). With `PROTON_BRIDGE_TLS_POLICY=best_effort` the server will continue on loopback only; with `pinned` it will refuse to start.                                                                                                                          |
| `CERTIFICATE_VERIFY_FAILED`                                                                | Happens with `PROTON_BRIDGE_TLS_POLICY=pinned` when the cert can't be read or doesn't match. Switch to `best_effort` to confirm everything else works, then fix the cert path. Bridge regenerates its cert on some upgrades — re-run `bootstrap.py` to recapture.                                                                                                                                |
| `WRONG_VERSION_NUMBER` (ssl error)                                                         | Wrong port. Check Bridge → *Advanced settings* and confirm IMAP/SMTP ports match `PROTON_BRIDGE_IMAP_PORT` / `PROTON_BRIDGE_SMTP_PORT`.                                                                                                                                                                                                                                                          |
| `[AUTH] LOGIN failed`                                                                      | App-password is wrong or expired. Regenerate in Bridge → *Mailbox details* and re-run `setup_keychain.sh` (or `bootstrap.py --force-password`).                                                                                                                                                                                                                                                  |
| `proton_search_emails` returns `uid: null` for every message                               | Older versions of this server used a FETCH spec that did not include `UID` in the data items list. Pull the latest source — the spec now includes `UID` explicitly.                                                                                                                                                                                                                              |
| `proton_create_draft` or `proton_send_email` fails with `ValueError: date_time must be aware` | Older versions called `imaplib.Time2Internaldate(datetime.now())` with a naive datetime. Python 3.12 deprecated this and 3.14 hard-rejects it. Pull the latest source — both call sites now pass a timezone-aware UTC datetime.                                                                                                                                                                  |
| MCP server fails to start after upgrading Python                                           | `__pycache__/` may contain bytecode compiled for the previous Python version. Delete it: `rm -rf <install-path>/proton-bridge-mcp/__pycache__`. Then restart Claude Desktop.                                                                                                                                                                                                                     |
| Connection drops mid-search                                                                | The pool reconnects automatically; re-issue the tool call. Persistent drops usually mean Bridge has been quit or its TLS cert was regenerated.                                                                                                                                                                                                                                                   |

## Threat model

- **Local-only**: this MCP server runs on your Mac under your user account. Bridge listens only on `127.0.0.1`. Nothing this server does talks to the public internet on your behalf — when Claude invokes a tool, the resulting IMAP/SMTP traffic stays on loopback to Bridge, and Bridge then talks to Proton over its own end-to-end-encrypted channel.
- **Credentials**: the Bridge app-password lives in the macOS Keychain, fetched per-process via `/usr/bin/security`. The Keychain item's ACL trusts the `security` CLI explicitly, so macOS does not gate every read with a prompt; conversely, no other process can read the password without macOS authentication. The password is never written to disk by this server, never logged, and never exposed in tool outputs.
- **TLS**: the connection to Bridge is always STARTTLS-wrapped. With `PROTON_BRIDGE_TLS_POLICY=pinned`, the server pins to Bridge's specific self-signed certificate (saved to `~/.config/proton-bridge-mcp/cert.pem` on first install). With `best_effort`, the server falls back to `CERT_NONE` on loopback only — acceptable because the only thing Bridge listens on is loopback under your own user account, but `pinned` is preferred where Bridge's cert is stable.
- **Send / destructive tools**: explicitly annotated. `proton_send_email`, `proton_delete_email`, `proton_move_email`, `proton_flag_email`, and `proton_create_draft` all carry MCP `destructiveHint` / `idempotentHint` annotations the client can use to gate confirmation. Reads default to non-mutating (`mark_seen=false`).
- **Prompt-injection caveat**: an MCP server that reads email is, by construction, a prompt-injection surface. Email bodies you read with `proton_read_email` may contain instructions intended to manipulate the model. Never have Claude execute actions described in inbound email content without your explicit approval. Treat all email content as untrusted input, even from senders you know.

## Development

```bash
# Re-generate hash-pinned requirements after changing top-level deps in requirements.in
uv pip compile requirements.in --generate-hashes --python-version 3.10 -o requirements.txt
# (or: pip-compile --generate-hashes --output-file requirements.txt requirements.in)

# Run a quick syntax check
python3 -c "import ast; ast.parse(open('proton_bridge_mcp.py').read())"
```

## License

MIT — see `LICENSE`.
