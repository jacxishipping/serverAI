from __future__ import annotations

import os

import pytest

from ai_bridge.control.db import connect


@pytest.mark.skipif(not os.environ.get("AI_BRIDGE_TEST_POSTGRES_URL"), reason="Set AI_BRIDGE_TEST_POSTGRES_URL to run PostgreSQL integration checks")
def test_postgres_pool_migrations_and_transaction() -> None:
    conn = connect(database_url=os.environ["AI_BRIDGE_TEST_POSTGRES_URL"])
    try:
        row = conn.execute("SELECT 1 AS alive").fetchone()
        assert row["alive"] == 1
        with conn.transaction():
            conn.execute("CREATE TEMP TABLE IF NOT EXISTS aibridge_pool_probe (value INTEGER)")
            conn.execute("INSERT INTO aibridge_pool_probe (value) VALUES (?)", (42,))
            row = conn.execute("SELECT value FROM aibridge_pool_probe").fetchone()
            assert row["value"] == 42
    finally:
        conn.close()
