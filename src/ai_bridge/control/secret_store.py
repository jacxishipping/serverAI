"""Database field encryption for provider and connector credentials.

The encryption key lives outside the database. Without a configured key,
development mode preserves legacy plaintext behavior; deployments can set
AI_BRIDGE_REQUIRE_SECRET_ENCRYPTION=1 to reject unencrypted secret writes.
"""
from __future__ import annotations

import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"
_MCP_COLUMNS = ("auth_token", "oauth_client_secret", "oauth_refresh_token", "headers_json")


class SecretStoreError(RuntimeError):
    """Raised when a secret cannot be protected or decrypted safely."""


def _fernet() -> Fernet | None:
    key = os.environ.get("AI_BRIDGE_DB_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    return _make_fernet(key)


def _make_fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise SecretStoreError("AI_BRIDGE_DB_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def validate_secret_store_config() -> None:
    required = os.environ.get("AI_BRIDGE_REQUIRE_SECRET_ENCRYPTION", "0").lower() in {"1", "true", "yes"}
    if required and _fernet() is None:
        raise SecretStoreError("AI_BRIDGE_REQUIRE_SECRET_ENCRYPTION is enabled but AI_BRIDGE_DB_ENCRYPTION_KEY is not set.")


def protect_secret(value: str | None) -> str:
    text = str(value or "")
    if not text or text.startswith(PREFIX):
        return text
    fernet = _fernet()
    if fernet is None:
        if os.environ.get("AI_BRIDGE_REQUIRE_SECRET_ENCRYPTION", "0").lower() in {"1", "true", "yes"}:
            raise SecretStoreError("Secret storage is disabled because AI_BRIDGE_DB_ENCRYPTION_KEY is not configured.")
        return text
    return PREFIX + fernet.encrypt(text.encode("utf-8")).decode("ascii")


def reveal_secret(value: str | None) -> str:
    text = str(value or "")
    if not text.startswith(PREFIX):
        return text
    fernet = _fernet()
    if fernet is None:
        raise SecretStoreError("Encrypted database secrets require AI_BRIDGE_DB_ENCRYPTION_KEY.")
    try:
        return fernet.decrypt(text[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeEncodeError, UnicodeDecodeError) as exc:
        raise SecretStoreError("Database secret decryption failed; verify the encryption key and backup.") from exc


def migrate_database_secrets(conn: Any) -> int:
    """Encrypt legacy plaintext secret fields in place when a key is configured."""
    if _fernet() is None:
        return 0
    changed = 0
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    for row in rows:
        key = str(row["key"] or "")
        value = str(row["value"] or "")
        is_secret = (
            key == "ai_default_key"
            or (key.startswith("ai_") and key.endswith("_key"))
            or key in {"webhook_url", "alert_webhooks"}
        )
        if value.startswith(PREFIX):
            reveal_secret(value)
        elif is_secret and value:
            conn.execute("UPDATE settings SET value=? WHERE key=?", (protect_secret(value), key))
            changed += 1

    servers = conn.execute(
        "SELECT id, auth_token, oauth_client_secret, oauth_refresh_token, headers_json FROM mcp_servers"
    ).fetchall()
    for row in servers:
        for column in _MCP_COLUMNS:
            if str(row[column] or "").startswith(PREFIX):
                reveal_secret(row[column])
        values = [protect_secret(row[column]) for column in _MCP_COLUMNS]
        original = [str(row[column] or "") for column in _MCP_COLUMNS]
        if values != original:
            conn.execute(
                "UPDATE mcp_servers SET auth_token=?, oauth_client_secret=?, oauth_refresh_token=?, headers_json=? WHERE id=?",
                (*values, row["id"]),
            )
            changed += sum(value != old for value, old in zip(values, original))
    if changed:
        conn.commit()
    return changed


def rotate_database_secrets(conn: Any, old_key: str, new_key: str) -> int:
    """Re-encrypt every protected credential field atomically with a new key."""
    if not old_key.strip() or not new_key.strip():
        raise SecretStoreError("Both old and new database encryption keys are required.")
    old_fernet = _make_fernet(old_key.strip())
    new_fernet = _make_fernet(new_key.strip())

    def rotate(value: Any) -> str:
        text = str(value or "")
        if not text:
            return text
        if text.startswith(PREFIX):
            try:
                plaintext = old_fernet.decrypt(text[len(PREFIX):].encode("ascii"))
            except (InvalidToken, UnicodeEncodeError) as exc:
                raise SecretStoreError("Credential rotation aborted: an encrypted field cannot be opened with the old key.") from exc
        else:
            plaintext = text.encode("utf-8")
        return PREFIX + new_fernet.encrypt(plaintext).decode("ascii")

    changed = 0
    with conn.transaction():
        settings = conn.execute("SELECT key, value FROM settings").fetchall()
        for row in settings:
            key = str(row["key"] or "")
            value = str(row["value"] or "")
            is_secret = (
                key == "ai_default_key"
                or (key.startswith("ai_") and key.endswith("_key"))
                or key in {"webhook_url", "alert_webhooks"}
            )
            if value.startswith(PREFIX) or (is_secret and value):
                conn.execute("UPDATE settings SET value=? WHERE key=?", (rotate(value), key))
                changed += 1

        servers = conn.execute(
            "SELECT id, auth_token, oauth_client_secret, oauth_refresh_token, headers_json FROM mcp_servers"
        ).fetchall()
        for row in servers:
            values = [rotate(row[column]) for column in _MCP_COLUMNS]
            originals = [str(row[column] or "") for column in _MCP_COLUMNS]
            if values != originals:
                conn.execute(
                    "UPDATE mcp_servers SET auth_token=?, oauth_client_secret=?, oauth_refresh_token=?, headers_json=? WHERE id=?",
                    (*values, row["id"]),
                )
                changed += sum(value != old for value, old in zip(values, originals))
    return changed
