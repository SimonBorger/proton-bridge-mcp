# Changelog

All notable changes to `proton-bridge-mcp` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `.claude-plugin/plugin.json` — Claude plugin manifest. Wraps the server with the metadata Claude Desktop and Claude Code expect when installing from a marketplace. Uses `${CLAUDE_PLUGIN_ROOT}` for portable `.venv` resolution.
- `.claude-plugin/marketplace.json` — self-hosted marketplace endpoint. Users can `/plugin marketplace add miketigerblue/proton-bridge-mcp` and install directly from the repo.
- `.mcp.json` — generic project-local stdio launch descriptor for `claude mcp add` and other MCP-capable clients that follow the convention.
- `server.json` — submission template for the official MCP Registry at `registry.modelcontextprotocol.io`. Reverse-DNS name `io.github.miketigerblue/proton-bridge-mcp`. The `packages.identifier` field assumes a PyPI artifact named `proton-bridge-mcp`; that must be published before this `server.json` can be submitted.
- `HANDOFF.md` — phase plan, conventions, and gotchas captured for any future contributor (or Code agent) picking up the project.
- README "Why this one?" section positioning the server against the existing Proton-MCP ecosystem on security and supply-chain hygiene rather than tool count.

### Fixed
- `proton_search_emails` and `proton_list_recent` now correctly return IMAP UIDs in their JSON output. The IMAP `FETCH` data-item list was missing the explicit `UID` token, which silently dropped UIDs from server responses on most Bridge versions; downstream tools that take a UID parameter (`proton_read_email`, `proton_flag_email`, `proton_move_email`, etc.) were therefore unusable against fresh search results.
- `proton_create_draft` and `proton_send_email` (with `save_to_sent=true`) no longer crash on Python 3.12+ runtimes. Both paths called `imaplib.Time2Internaldate(datetime.now())` with a naive datetime, which Python 3.12 began rejecting and Python 3.14 hard-rejects with `ValueError: date_time must be aware`. Both call sites now pass a timezone-aware UTC datetime.

### Changed
- `setup_keychain.sh` now stores the Bridge app-password with `-T /usr/bin/security` instead of `-T ""`. The previous setting registered no trusted apps on the keychain item, which caused macOS to re-prompt on every MCP process spawn and prevented `Always Allow` from persisting. With `/usr/bin/security` on the trusted-applications list the keychain ACL matches the binary the MCP shells out to, and the prompt-loop disappears.
- README troubleshooting section expanded with the four post-install gotchas surfaced in real-world use: stale `__pycache__` from a Python-version bump, naive datetime on 3.12+, missing UID in FETCH spec, and the keychain ACL prompt-loop.

### Security
- Tightened `.gitignore` to refuse credentials, TLS material (`*.pem`/`*.crt`/`*.key`/`cert.pem`), live Claude Desktop config, and dotenv files. The `*.example.json` files are still tracked.

## [0.1.0] - 2026-04-24

### Added
- Initial release. Local MCP server exposing Proton Mail Bridge over loopback IMAP/SMTP.
- Ten tools: `proton_list_folders`, `proton_list_recent`, `proton_search_emails`, `proton_read_email`, `proton_download_attachment`, `proton_flag_email`, `proton_move_email`, `proton_delete_email`, `proton_send_email`, `proton_create_draft`.
- TLS pinning to the Bridge self-signed cert; falls back to localhost-only `CERT_NONE` when cert can't be located, controllable via `PROTON_BRIDGE_TLS_POLICY`.
- Credential resolution from macOS Keychain with env-var fallback; never persists credentials to disk.
- Pooled IMAP/SMTP connections behind asyncio locks with auto-reconnect.
- `bootstrap.py` one-shot installer (venv, deps, TOFU cert capture, Keychain setup, end-to-end IMAP login verification, Claude Desktop config merge).
- Manual install path via `install.sh` + `setup_keychain.sh` for users who prefer fine control.
