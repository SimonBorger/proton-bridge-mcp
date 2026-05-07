#!/usr/bin/env python3
"""
One-command bootstrap for the Proton Bridge MCP server.

Does EVERYTHING from zero to working (except one prompt for the Bridge
app-password you have to copy from Bridge's UI). Re-runnable — each step
is skipped if already done.

Run:
    /usr/bin/python3 bootstrap.py

Steps:
    1. Create .venv next to this script (if missing)
    2. Install mcp[cli] + pydantic into it
    3. Learn Bridge's TLS certificate via STARTTLS → ~/.config/proton-bridge-mcp/cert.pem
    4. Prompt once for the Bridge app-password (strips whitespace) → macOS Keychain
    5. Verify IMAP login end-to-end
    6. Merge the proton_bridge MCP block into ~/Library/Application Support/Claude/claude_desktop_config.json
"""
from __future__ import annotations

import getpass
import hashlib
import imaplib
import json
import os
import pathlib
import re
import ssl
import subprocess
import sys
import venv

HERE = pathlib.Path(__file__).resolve().parent
VENV = HERE / ".venv"
SERVER_PY = HERE / "proton_bridge_mcp.py"
CERT_PATH = pathlib.Path.home() / ".config/proton-bridge-mcp/cert.pem"
CLAUDE_CFG = (
    pathlib.Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
)

KC_SERVICE = "proton_bridge_mcp"
HOST = "127.0.0.1"
IMAP_PORT = 1143


GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def step(msg: str) -> None:
    print(f"\n{YELLOW}▶{RESET} {msg}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def skip(msg: str) -> None:
    print(f"  {DIM}· {msg}{RESET}")


def die(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------- #
# 1. venv
# --------------------------------------------------------------------------- #
def ensure_venv() -> None:
    if (VENV / "bin/python").exists():
        skip(f"venv already at {VENV}")
        return
    step("Creating Python venv")
    venv.create(VENV, with_pip=True)
    ok(f"venv at {VENV}")


def ensure_deps() -> None:
    step("Installing hash-pinned runtime deps into venv")
    pip = VENV / "bin/pip"
    subprocess.run([str(pip), "install", "-q", "--upgrade", "pip"], check=True)
    requirements = HERE / "requirements.txt"
    if requirements.is_file():
        # --require-hashes makes pip refuse to install anything that doesn't match
        # the hash list in requirements.txt. Catches supply-chain tampering.
        subprocess.run(
            [str(pip), "install", "-q", "--require-hashes", "-r", str(requirements)],
            check=True,
        )
    else:
        # Fallback for ad-hoc installs without the lock file present.
        subprocess.run([str(pip), "install", "-q", "mcp[cli]", "pydantic"], check=True)
    ok("deps installed")


# --------------------------------------------------------------------------- #
# 2. cert (TOFU)
# --------------------------------------------------------------------------- #
def _tofu_ctx() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def ensure_cert() -> None:
    if CERT_PATH.exists():
        skip(f"cert already saved at {CERT_PATH}")
        return
    step("Capturing Bridge TLS cert via STARTTLS (trust-on-first-use)")
    try:
        c = imaplib.IMAP4(HOST, IMAP_PORT, timeout=10)
        c.starttls(ssl_context=_tofu_ctx())
        der = c.sock.getpeercert(binary_form=True)
        try:
            c.logout()
        except Exception:
            pass
    except Exception as e:
        die(f"could not reach Bridge on {HOST}:{IMAP_PORT} — is it running? ({e})")
    if not der:
        die("Bridge presented no certificate during STARTTLS")
    pem = ssl.DER_cert_to_PEM_cert(der)
    CERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CERT_PATH.write_text(pem)
    os.chmod(CERT_PATH, 0o600)
    fp = hashlib.sha256(der).hexdigest().upper()
    fp = ":".join(fp[i:i+2] for i in range(0, len(fp), 2))
    ok(f"saved cert → {CERT_PATH}")
    print(f"    {DIM}SHA-256 {fp}{RESET}")


# --------------------------------------------------------------------------- #
# 3. username + Keychain password
# --------------------------------------------------------------------------- #
def prompt_user() -> str:
    u = os.environ.get("PROTON_BRIDGE_USER", "").strip()
    if u:
        return u
    step("Bridge username")
    u = input("  Paste username shown in Bridge → Mailbox details: ").strip()
    if not u:
        die("username is required")
    return u


def _kc_get(user: str) -> str | None:
    r = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", KC_SERVICE, "-a", user, "-w"],
        capture_output=True, text=True, check=False, timeout=5,
    )
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def ensure_keychain(user: str, force: bool = False) -> str:
    existing = _kc_get(user)
    if existing and not force:
        skip(f"keychain entry exists for {user} ({len(existing)} chars)")
        return existing
    step(f"Storing Bridge app-password in Keychain (service={KC_SERVICE}, account={user})")
    raw = getpass.getpass("  Paste Bridge app-password (copy from Bridge UI; input hidden): ")
    pw = re.sub(r"\s+", "", raw)
    if not pw:
        die("empty password")
    subprocess.run(
        ["/usr/bin/security", "add-generic-password", "-U",
         "-s", KC_SERVICE, "-a", user, "-w", pw],
        check=True,
    )
    ok(f"stored ({len(pw)} chars)")
    return pw


# --------------------------------------------------------------------------- #
# 4. end-to-end IMAP login
# --------------------------------------------------------------------------- #
def verify_login(user: str, password: str) -> None:
    step("Verifying IMAP login with pinned cert")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cafile=str(CERT_PATH))
    c = imaplib.IMAP4(HOST, IMAP_PORT, timeout=10)
    c.starttls(ssl_context=ctx)
    try:
        typ, _ = c.login(user, password)
    except imaplib.IMAP4.error as e:
        die(f"LOGIN failed: {e}. Re-run with --force-password and paste again.")
    if typ != "OK":
        die(f"LOGIN returned {typ!r}")
    typ, data = c.list()
    c.logout()
    if typ != "OK":
        die(f"LIST returned {typ!r}")
    ok(f"LOGIN OK — {len(data or [])} folders visible")


# --------------------------------------------------------------------------- #
# 5. Claude Desktop config merge
# --------------------------------------------------------------------------- #
def merge_config(user: str) -> None:
    step(f"Merging MCP block into {CLAUDE_CFG}")
    CLAUDE_CFG.parent.mkdir(parents=True, exist_ok=True)
    cfg: dict = {}
    if CLAUDE_CFG.exists():
        try:
            cfg = json.loads(CLAUDE_CFG.read_text() or "{}")
        except json.JSONDecodeError:
            die(f"existing config is not valid JSON: {CLAUDE_CFG}. Fix manually and rerun.")
    entry = {
        "command": str(VENV / "bin/python"),
        "args": [str(SERVER_PY)],
        "env": {
            "PROTON_BRIDGE_USER": user,
            "PROTON_BRIDGE_CERT_PATH": str(CERT_PATH),
            "PROTON_BRIDGE_TLS_POLICY": "pinned",
            "PROTON_BRIDGE_DEFAULT_FROM": user,
            "PROTON_BRIDGE_LOG_LEVEL": "INFO",
        },
    }
    mcps = cfg.setdefault("mcpServers", {})
    if mcps.get("proton_bridge") == entry:
        skip("Claude config already up to date")
        return
    mcps["proton_bridge"] = entry
    CLAUDE_CFG.write_text(json.dumps(cfg, indent=2) + "\n")
    ok("proton_bridge block written (other MCP servers preserved)")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    if sys.platform != "darwin":
        die("This bootstrap uses macOS Keychain and paths; macOS only.")

    force_password = "--force-password" in sys.argv

    print(f"{DIM}Proton Bridge MCP bootstrap — one-shot setup{RESET}")
    ensure_venv()
    ensure_deps()
    ensure_cert()
    user = prompt_user()
    password = ensure_keychain(user, force=force_password)
    verify_login(user, password)
    merge_config(user)

    print()
    print(f"{GREEN}All steps complete.{RESET} Quit Claude Desktop (⌘Q) and relaunch,")
    print("then in a new conversation: “list my Proton folders”.")


if __name__ == "__main__":
    main()
