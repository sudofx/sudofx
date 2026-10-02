"""Encrypted disposable transport for the Conversation browser gateway.

This module protects plaintext while it crosses GitHub workflow infrastructure.
It is not authoritative storage.  The transport key is supplied at runtime and
must never be committed.

Construction: AES-256-CBC with PKCS#7 padding via OpenSSL, then HMAC-SHA256 over
version || IV || ciphertext using an independent key (encrypt-then-MAC).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import subprocess
from pathlib import Path

TRANSPORT_ENV = "CONVERSATION_TRANSPORT_KEY"
VERSION = 1


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _keys(encoded: str | None = None) -> tuple[bytes, bytes]:
    raw_value = (encoded if encoded is not None else os.environ.get(TRANSPORT_ENV, "")).strip()
    if not raw_value:
        raise RuntimeError(f"{TRANSPORT_ENV} is required")
    try:
        material = _b64d(raw_value)
    except Exception as error:
        raise ValueError(f"{TRANSPORT_ENV} must be URL-safe base64") from error
    if len(material) != 64:
        raise ValueError(f"{TRANSPORT_ENV} must decode to exactly 64 bytes")
    return material[:32], material[32:]


def _openssl_cbc(data: bytes, *, key: bytes, iv: bytes, decrypt: bool) -> bytes:
    command = [
        "openssl",
        "enc",
        "-aes-256-cbc",
        "-nosalt",
        "-K",
        key.hex(),
        "-iv",
        iv.hex(),
    ]
    if decrypt:
        command.append("-d")
    completed = subprocess.run(
        command,
        input=data,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise ValueError("conversation transport decryption failed" if decrypt else "conversation transport encryption failed")
    return completed.stdout


def encrypt_text(text: str, *, key_value: str | None = None) -> str:
    if not isinstance(text, str):
        raise TypeError("transport plaintext must be text")
    encryption_key, authentication_key = _keys(key_value)
    iv = secrets.token_bytes(16)
    ciphertext = _openssl_cbc(text.encode("utf-8"), key=encryption_key, iv=iv, decrypt=False)
    authenticated = bytes([VERSION]) + iv + ciphertext
    mac = hmac.new(authentication_key, authenticated, hashlib.sha256).digest()
    return json.dumps(
        {"v": VERSION, "iv": _b64e(iv), "ct": _b64e(ciphertext), "mac": _b64e(mac)},
        sort_keys=True,
        separators=(",", ":"),
    )


def decrypt_text(envelope: str, *, key_value: str | None = None) -> str:
    encryption_key, authentication_key = _keys(key_value)
    try:
        payload = json.loads(envelope)
    except json.JSONDecodeError as error:
        raise ValueError("conversation transport envelope is invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"v", "iv", "ct", "mac"}:
        raise ValueError("conversation transport envelope shape is invalid")
    if payload["v"] != VERSION:
        raise ValueError("conversation transport version is unsupported")
    try:
        iv = _b64d(payload["iv"])
        ciphertext = _b64d(payload["ct"])
        supplied_mac = _b64d(payload["mac"])
    except Exception as error:
        raise ValueError("conversation transport envelope contains invalid base64") from error
    if len(iv) != 16 or not ciphertext:
        raise ValueError("conversation transport envelope contains invalid ciphertext")
    authenticated = bytes([VERSION]) + iv + ciphertext
    expected_mac = hmac.new(authentication_key, authenticated, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_mac, supplied_mac):
        raise ValueError("conversation transport authentication failed")
    plaintext = _openssl_cbc(ciphertext, key=encryption_key, iv=iv, decrypt=True)
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("conversation transport plaintext is not UTF-8") from error


def write_encrypted_reply(response_path: Path, output_path: Path, request_id: str) -> None:
    response = response_path.read_text(encoding="utf-8")
    if not request_id or len(request_id) > 128:
        raise ValueError("request_id is invalid")
    document = {
        "projection_kind": "conversation_encrypted_reply",
        "projection_schema": 1,
        "request_id": request_id,
        "payload": json.loads(encrypt_text(response)),
    }
    output_path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    decrypt_parser = sub.add_parser("decrypt")
    decrypt_parser.add_argument("envelope")

    encrypt_parser = sub.add_parser("encrypt")
    encrypt_parser.add_argument("text")

    reply_parser = sub.add_parser("reply")
    reply_parser.add_argument("--response-file", required=True)
    reply_parser.add_argument("--output-file", required=True)
    reply_parser.add_argument("--request-id", required=True)

    args = parser.parse_args()
    if args.command == "decrypt":
        print(decrypt_text(args.envelope), end="")
    elif args.command == "encrypt":
        print(encrypt_text(args.text), end="")
    else:
        write_encrypted_reply(
            Path(args.response_file),
            Path(args.output_file),
            args.request_id,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
