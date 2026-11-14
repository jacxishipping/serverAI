from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_bridge.control.app import _claim_schedule_occurrence, _claim_trigger_cooldown
from ai_bridge.control.custom_agents import _claim_agent_run
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


@pytest.mark.skipif(not os.environ.get("AI_BRIDGE_TEST_POSTGRES_URL"), reason="Set AI_BRIDGE_TEST_POSTGRES_URL to run PostgreSQL integration checks")
def test_postgres_scheduler_claims_are_single_winner() -> None:
    conn = connect(database_url=os.environ["AI_BRIDGE_TEST_POSTGRES_URL"])
    suffix = uuid.uuid4().hex
    schedule_id, agent_id, trigger_id = f"sched-{suffix}", f"agent-{suffix}", f"trigger-{suffix}"
    now = time.time()
    try:
        conn.execute(
            "INSERT INTO schedules (id, name, tool, next_run_at, created_at) VALUES (?,?,?,?,?)",
            (schedule_id, "claim probe", "get_system_info", now - 1, now - 1),
        )
        conn.execute(
            "INSERT INTO custom_agents (id, name, instruction, next_run_at, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (agent_id, "claim probe", "probe", now - 1, now - 1, now - 1),
        )
        conn.execute(
            "INSERT INTO triggers (id, name, metric, threshold, action_target, created_at) VALUES (?,?,?,?,?,?)",
            (trigger_id, "claim probe", "cpu_percent", 100, "notify", now - 1),
        )
        conn.commit()

        def race(claim):
            def attempt(_):
                won = claim()
                if won:
                    conn.commit()
                return won
            with ThreadPoolExecutor(max_workers=2) as executor:
                return list(executor.map(attempt, range(2)))

        assert sum(race(lambda: _claim_schedule_occurrence(conn, schedule_id, now, 60))) == 1
        assert sum(race(lambda: _claim_agent_run(conn, agent_id, now, 60))) == 1
        assert sum(race(lambda: _claim_trigger_cooldown(conn, trigger_id, now, 300))) == 1
    finally:
        conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
        conn.execute("DELETE FROM custom_agents WHERE id=?", (agent_id,))
        conn.execute("DELETE FROM triggers WHERE id=?", (trigger_id,))
        conn.commit()
        conn.close()
