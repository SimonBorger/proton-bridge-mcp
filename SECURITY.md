# Security Policy

`proton-bridge-mcp` runs on your Mac, holds a Proton Bridge app-password in your
macOS Keychain, and reads inbound email on your behalf. Vulnerabilities here
matter. This document covers how to report them and what guarantees the server
does and does not make.

## Supported versions

| Version  | Supported |
| -------- | --------- |
| `main` (latest commit) | yes |
| Latest tagged release | yes |
| All other tagged releases | no — upgrade |
| Forks                | not by this repo |

There is no LTS branch. Fixes land on `main` and are picked up in the next tag.

## Reporting a vulnerability

**Use GitHub Security Advisories.** This keeps the disclosure private until a
fix is ready.

1. Open <https://github.com/miketigerblue/proton-bridge-mcp/security/advisories/new>.
2. Include: affected versions, reproduction steps, observed vs. expected
   behaviour, and (if known) suggested mitigation.
3. Expect an initial acknowledgement within 5 working days. A coordinated
   disclosure window of up to 90 days is the working default; shorter windows
   are negotiable for actively-exploited issues.

Please do **not** open a public GitHub issue, PR, or discussion for a
security-impacting bug. Public reports get fixed, but the people most likely to
weaponise them get a head start.

If you cannot use GitHub Security Advisories, email
[mike@tigerblue.io](mailto:mike@tigerblue.io) with `[proton-bridge-mcp
security]` in the subject. PGP key is on the keyservers under the same
address; ask if you need it inline.

## Threat model

What this server protects against and what it doesn't.

### In scope

- **Loopback isolation.** Bridge listens only on `127.0.0.1`. The MCP server
  speaks to Bridge over loopback IMAP/SMTP. No traffic crosses your network as
  a result of an MCP tool call. Bridge's own outbound channel to Proton is
  end-to-end encrypted and out of this repo's control.
- **Credential confidentiality at rest.** The Bridge app-password lives in the
  macOS Keychain. The keychain item's ACL trusts only `/usr/bin/security`. The
  password is never written to disk by this server, never logged, and never
  appears in tool outputs.
- **Supply-chain integrity at install.** `requirements.txt` is hash-pinned;
  every transitive dependency is verified against a known-good sha256 at
  install. Tampered wheels on PyPI fail loudly. `bootstrap.py` and
  `install.sh` both pass `--require-hashes`.
- **TLS to Bridge.** STARTTLS is always negotiated. With
  `PROTON_BRIDGE_TLS_POLICY=pinned`, the connection refuses to start unless
  Bridge presents the cert captured during first-run TOFU. With `best_effort`
  (default), the server falls back to `CERT_NONE` on loopback only.
- **Read semantics.** `proton_read_email` defaults `mark_seen=false`. Reading
  a message never implicitly marks it seen.
- **Mutating tools are annotated.** `proton_send_email`, `proton_delete_email`,
  `proton_move_email`, `proton_flag_email`, and `proton_create_draft` all
  carry MCP `destructiveHint` / `idempotentHint` annotations the client can
  use to gate confirmation.

### Out of scope (intentionally not protected)

- **Compromise of the host machine.** A local attacker with code execution as
  your user can read the keychain and intercept loopback traffic. This is
  outside the threat model — same as for any MCP server, mail client, or
  password manager on the same box.
- **Compromise of Proton Mail Bridge itself.** This server treats Bridge as
  trusted. If Bridge is compromised, Bridge's own threat model applies, not
  ours.
- **Prompt injection from inbound mail content.** This is a real risk and
  cannot be mitigated by the server alone. Email bodies are untrusted input.
  Any feature that lets the model take action based on email content
  (auto-reply, auto-forward, rule-based delete) **must** require explicit
  per-action user confirmation in the MCP client. The server provides the
  primitives; the client and the operator provide the policy.
- **Attacks against Proton's infrastructure or end-to-end-encryption design.**
  Out of this repo's hands.
- **Non-macOS platforms.** Linux and Windows are unsupported. Bridge runs
  there, but the credential-storage and process-spawn assumptions in this
  server are macOS-specific. Don't deploy it elsewhere.

## Security properties to verify

Anyone auditing the server should be able to confirm the following from the
source:

- `requirements.txt` is generated with `--generate-hashes`; nothing else gets
  installed. (`install.sh` and `bootstrap.py` both assert this.)
- The keychain item for `proton_bridge_mcp` has `/usr/bin/security` on its
  trusted-applications ACL. (`setup_keychain.sh` and `bootstrap.py` set this
  with `-T /usr/bin/security`.)
- The MCP server fetches the password by invoking `/usr/bin/security` per
  process; the password is not cached on disk.
- `PROTON_BRIDGE_TLS_POLICY=pinned` causes the server to refuse to start when
  the captured cert can't be loaded.
- No credential, cert path, or message body is logged at `INFO` or `DEBUG`.

If any of these is no longer true, that itself is a security bug — please
report it via the channel above.

## Hardening recommendations for operators

- Run with `PROTON_BRIDGE_TLS_POLICY=pinned` once `bootstrap.py` has captured
  Bridge's cert. The `best_effort` default exists for first-install
  ergonomics, not as the long-term posture.
- Keep Bridge up to date. Bridge regenerates its TLS cert on some upgrades; in
  pinned mode, that means re-running `bootstrap.py` (the cert capture step).
- Review the MCP client's destructive-action confirmation policy. Never let
  the model auto-execute send/delete/move based on inbound email content.
- Rotate the Bridge app-password periodically via Bridge → *Mailbox details*,
  followed by `setup_keychain.sh` (or `bootstrap.py --force-password`).
