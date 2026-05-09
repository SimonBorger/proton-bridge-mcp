"""Unit tests for the pure helpers in proton_bridge_mcp.

These tests deliberately exercise only the side-effect-free helpers: header
decoding, address parsing, IMAP-quoting, body extraction, and IMAP-search
criteria construction. Anything that touches the network (IMAP, SMTP) or the
keychain is out of scope here -- those need integration coverage with a real
or simulated Bridge.
"""
from __future__ import annotations

import email
from email.message import EmailMessage

import proton_bridge_mcp as pbm


# ----------------------------------------------------------------------------
# _decode_header
# ----------------------------------------------------------------------------
class TestDecodeHeader:
    def test_none_returns_empty_string(self):
        assert pbm._decode_header(None) == ""

    def test_plain_ascii_passes_through(self):
        assert pbm._decode_header("Hello, world") == "Hello, world"

    def test_bytes_decoded_as_utf8(self):
        assert pbm._decode_header("Olá".encode("utf-8")) == "Olá"

    def test_latin1_fallback_on_invalid_utf8(self):
        # Bytes that are not valid UTF-8 should still decode to *some* string
        # rather than raise. The current implementation replaces invalid
        # sequences; the property under test is "no exception, returns str".
        out = pbm._decode_header(b"\xc3\x28")  # invalid utf-8
        assert isinstance(out, str)
        assert out  # non-empty

    def test_rfc2047_qp_encoded_word(self):
        # =?UTF-8?Q?Caf=C3=A9?= → "Café"
        assert pbm._decode_header("=?UTF-8?Q?Caf=C3=A9?=") == "Café"

    def test_rfc2047_base64_encoded_word(self):
        # "Hello" in UTF-8 base64
        assert pbm._decode_header("=?utf-8?B?SGVsbG8=?=") == "Hello"

    def test_mixed_encoded_and_plain(self):
        out = pbm._decode_header("=?UTF-8?Q?Caf=C3=A9?= - lunch")
        assert "Café" in out
        assert "lunch" in out


# ----------------------------------------------------------------------------
# _iso_date
# ----------------------------------------------------------------------------
class TestIsoDate:
    def test_none_returns_none(self):
        assert pbm._iso_date(None) is None

    def test_empty_string_returns_none(self):
        assert pbm._iso_date("") is None

    def test_valid_rfc2822_returns_iso(self):
        out = pbm._iso_date("Mon, 09 Mar 2026 14:30:00 +0000")
        # We don't pin the exact tz offset (depends on the runner) but we
        # require: ISO format, 2026, March, the 9th.
        assert out is not None
        assert "2026-03-09" in out
        assert "T" in out  # ISO 8601 separator

    def test_malformed_returns_input_unchanged_or_none(self):
        # Implementation choice: parsedate_to_datetime may return None for
        # garbage. Whatever happens, the helper must not raise.
        out = pbm._iso_date("not a date at all")
        assert out is None or "not a date" in out


# ----------------------------------------------------------------------------
# _quote (IMAP string quoting)
# ----------------------------------------------------------------------------
class TestQuote:
    def test_simple_string(self):
        assert pbm._quote("hello") == '"hello"'

    def test_escapes_double_quote(self):
        assert pbm._quote('say "hi"') == r'"say \"hi\""'

    def test_escapes_backslash(self):
        assert pbm._quote(r"a\b") == r'"a\\b"'

    def test_escapes_both_backslash_and_quote(self):
        assert pbm._quote(r'a\"b') == r'"a\\\"b"'

    def test_empty_string(self):
        assert pbm._quote("") == '""'


# ----------------------------------------------------------------------------
# _addr_struct
# ----------------------------------------------------------------------------
class TestAddrStruct:
    def test_empty_returns_empty_list(self):
        assert pbm._addr_struct("") == []

    def test_single_bare_address(self):
        out = pbm._addr_struct("alice@example.com")
        assert out == [{"name": "", "email": "alice@example.com"}]

    def test_single_with_display_name(self):
        out = pbm._addr_struct("Alice <alice@example.com>")
        assert out == [{"name": "Alice", "email": "alice@example.com"}]

    def test_multiple_addresses(self):
        out = pbm._addr_struct("Alice <alice@example.com>, bob@example.com")
        assert {"name": "Alice", "email": "alice@example.com"} in out
        assert {"name": "", "email": "bob@example.com"} in out
        assert len(out) == 2

    def test_rfc2047_in_display_name(self):
        out = pbm._addr_struct("=?UTF-8?Q?Caf=C3=A9?= <cafe@example.com>")
        assert out == [{"name": "Café", "email": "cafe@example.com"}]

    def test_drops_entries_without_email(self):
        # Display-only entries with no actual mailbox shouldn't survive.
        out = pbm._addr_struct("undisclosed-recipients:;")
        assert all(e["email"] for e in out)


# ----------------------------------------------------------------------------
# _parse_flags
# ----------------------------------------------------------------------------
class TestParseFlags:
    def test_no_flags_returns_empty(self):
        assert pbm._parse_flags("UID 42 RFC822.SIZE 1234") == []

    def test_seen_flag(self):
        assert pbm._parse_flags(r"FLAGS (\Seen) UID 42") == [r"\Seen"]

    def test_multiple_flags(self):
        assert pbm._parse_flags(r"FLAGS (\Seen \Flagged) UID 42") == [r"\Seen", r"\Flagged"]

    def test_empty_flags(self):
        assert pbm._parse_flags("FLAGS () UID 42") == []


# ----------------------------------------------------------------------------
# _extract_body
# ----------------------------------------------------------------------------
class TestExtractBody:
    def test_plain_only(self):
        msg = EmailMessage()
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Subject"] = "test"
        msg.set_content("hello world")
        plain, html, attachments = pbm._extract_body(msg)
        assert "hello world" in plain
        assert html == ""
        assert attachments == []

    def test_html_only(self):
        msg = EmailMessage()
        msg["Subject"] = "test"
        msg.set_content("<p>hi</p>", subtype="html")
        plain, html, attachments = pbm._extract_body(msg)
        assert "<p>hi</p>" in html
        assert plain == ""
        assert attachments == []

    def test_multipart_alternative(self):
        msg = EmailMessage()
        msg["Subject"] = "test"
        msg.set_content("plain version")
        msg.add_alternative("<p>html version</p>", subtype="html")
        plain, html, attachments = pbm._extract_body(msg)
        assert "plain version" in plain
        assert "html version" in html
        assert attachments == []

    def test_attachment_metadata_only_no_payload(self):
        msg = EmailMessage()
        msg["Subject"] = "with attach"
        msg.set_content("see attached")
        msg.add_attachment(b"PDFCONTENT", maintype="application",
                           subtype="pdf", filename="report.pdf")
        plain, html, attachments = pbm._extract_body(msg)
        assert "see attached" in plain
        assert len(attachments) == 1
        attach = attachments[0]
        assert attach["filename"] == "report.pdf"
        assert attach["content_type"] == "application/pdf"
        assert attach["size_bytes"] > 0
        # Critical: attachment payload must NOT leak into the body.
        assert "PDFCONTENT" not in plain
        assert "PDFCONTENT" not in html

    def test_body_truncated_at_max_chars(self):
        big = "x" * (pbm.MAX_BODY_CHARS + 5000)
        msg = EmailMessage()
        msg["Subject"] = "huge"
        msg.set_content(big)
        plain, _, _ = pbm._extract_body(msg)
        assert len(plain) <= pbm.MAX_BODY_CHARS


# ----------------------------------------------------------------------------
# _build_search
# ----------------------------------------------------------------------------
class TestBuildSearch:
    def test_empty_returns_all(self):
        assert pbm._build_search() == ["ALL"]

    def test_single_from_filter(self):
        out = pbm._build_search(from_addr="alice@example.com")
        assert out[0] == "FROM"
        assert "alice@example.com" in out[1]

    def test_subject_filter_is_quoted(self):
        out = pbm._build_search(subject='hello "world"')
        assert "SUBJECT" in out
        # Embedded double-quotes must be escaped in the IMAP-quoted string.
        joined = " ".join(out)
        assert r'\"world\"' in joined

    def test_unseen_flag(self):
        out = pbm._build_search(unseen=True)
        assert "UNSEEN" in out

    def test_seen_flag(self):
        out = pbm._build_search(seen=True)
        assert "SEEN" in out

    def test_flagged_flag(self):
        out = pbm._build_search(flagged=True)
        assert "FLAGGED" in out

    def test_multiple_filters_combined(self):
        out = pbm._build_search(
            from_addr="alice@example.com",
            subject="invoice",
            unseen=True,
        )
        assert "FROM" in out
        assert "SUBJECT" in out
        assert "UNSEEN" in out

    def test_since_iso_date_converted_to_imap_format(self):
        out = pbm._build_search(since="2026-03-09")
        assert "SINCE" in out
        idx = out.index("SINCE")
        # IMAP wants DD-Mon-YYYY (e.g., "09-Mar-2026"); RFC 3501 §6.4.4.
        assert out[idx + 1] == "09-Mar-2026"

    def test_since_iso_datetime_with_z_converted(self):
        out = pbm._build_search(since="2026-03-09T14:30:00Z")
        idx = out.index("SINCE")
        assert out[idx + 1] == "09-Mar-2026"

    def test_not_keyword_emits_three_tokens(self):
        out = pbm._build_search(not_keyword="$Junk")
        assert out[:2] == ["NOT", "KEYWORD"]
        assert "$Junk" in out[2]


# ----------------------------------------------------------------------------
# _locate_bridge_cert (path search; no network)
# ----------------------------------------------------------------------------
class TestLocateBridgeCert:
    def test_explicit_override_path_used_when_present(self, tmp_path, monkeypatch):
        # Override path takes precedence over the candidates list.
        cert = tmp_path / "cert.pem"
        cert.write_text("-----BEGIN CERTIFICATE-----\nstub\n-----END CERTIFICATE-----\n")
        monkeypatch.setattr(pbm, "BRIDGE_CERT_PATH", str(cert))
        assert pbm._locate_bridge_cert() == cert

    def test_explicit_override_missing_returns_none(self, monkeypatch, tmp_path):
        # Override pointing at a nonexistent file should *not* fall through to
        # the candidates list -- the user clearly meant *that* path.
        nope = tmp_path / "does-not-exist.pem"
        monkeypatch.setattr(pbm, "BRIDGE_CERT_PATH", str(nope))
        assert pbm._locate_bridge_cert() is None
