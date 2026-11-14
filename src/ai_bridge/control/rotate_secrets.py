"""Rotate Fernet encryption for database-stored provider and MCP credentials.

Set the old key as AI_BRIDGE_DB_ENCRYPTION_KEY and the replacement as
AI_BRIDGE_DB_ENCRYPTION_KEY_NEW. Stop all control-plane processes first.
"""
from __future__ import annotations

import os
import sys

from . import db
from .secret_store import SecretStoreError, rotate_database_secrets


def main() -> None:
    old_key = os.environ.get("AI_BRIDGE_DB_ENCRYPTION_KEY", "").strip()
    new_key = os.environ.get("AI_BRIDGE_DB_ENCRYPTION_KEY_NEW", "").strip()
    if not old_key or not new_key:
        print(
            "Set AI_BRIDGE_DB_ENCRYPTION_KEY (current key) and "
            "AI_BRIDGE_DB_ENCRYPTION_KEY_NEW (replacement key) in the process environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if old_key == new_key:
        print("The replacement key must differ from the current key.", file=sys.stderr)
        raise SystemExit(2)

    conn = None
    try:
        conn = db.connect()
        changed = rotate_database_secrets(conn, old_key, new_key)
    except SecretStoreError as exc:
        print(f"Credential rotation did not complete; keep the current key configured: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        if conn is not None:
            conn.close()
    print(f"Credential rotation completed: {changed} encrypted fields updated.")
    print("Update AI_BRIDGE_DB_ENCRYPTION_KEY to the replacement key before restarting the service.")


if __name__ == "__main__":
    main()
