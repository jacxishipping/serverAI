from __future__ import annotations

from ai_bridge.control import db as dbmod
from ai_bridge.control.app import _claim_schedule_occurrence, _claim_trigger_cooldown
from ai_bridge.control.custom_agents import _claim_agent_run


def test_due_schedule_and_agent_occurrences_are_claimed_once_across_connections(tmp_path):
    db_path = tmp_path / "scheduler-claims.db"
    first = dbmod.connect(db_path=db_path)
    second = dbmod.connect(db_path=db_path)
    now = dbmod.now()
    first.execute(
        "INSERT INTO schedules (id, name, tool, next_run_at, created_at) VALUES (?,?,?,?,?)",
        ("schedule-1", "Daily check", "get_system_info", now - 1, now - 10),
    )
    first.execute(
        "INSERT INTO custom_agents (id, name, instruction, next_run_at, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("agent-1", "Inspector", "Inspect host", now - 1, now - 10, now - 10),
    )
    first.commit()

    assert _claim_schedule_occurrence(first, "schedule-1", now, 60) is True
    first.commit()
    assert _claim_schedule_occurrence(second, "schedule-1", now, 60) is False

    assert _claim_agent_run(first, "agent-1", now, 60) is True
    first.commit()
    assert _claim_agent_run(second, "agent-1", now, 60) is False
    assert first.execute("SELECT status FROM custom_agents WHERE id='agent-1'").fetchone()["status"] == "running"


def test_trigger_cooldown_claim_is_atomic_across_connections(tmp_path):
    db_path = tmp_path / "trigger-claims.db"
    first = dbmod.connect(db_path=db_path)
    second = dbmod.connect(db_path=db_path)
    now = dbmod.now()
    first.execute(
        "INSERT INTO triggers (id, name, metric, threshold, action_target, created_at) VALUES (?,?,?,?,?,?)",
        ("trigger-1", "High CPU", "cpu_percent", 90, "notify", now - 1),
    )
    first.commit()

    assert _claim_trigger_cooldown(first, "trigger-1", now, 300) is True
    first.commit()
    assert _claim_trigger_cooldown(second, "trigger-1", now + 1, 300) is False
