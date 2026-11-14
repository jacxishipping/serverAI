from __future__ import annotations

from fastapi.testclient import TestClient

from ai_bridge.control.app import create_app

ADMIN = "task-transition-test-token"


def _running_task(client: TestClient) -> tuple[str, str]:
    enrolled = client.post(
        "/api/devices/enroll",
        json={"name": "state-transition-test", "hostname": "host", "os": "linux"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"device_id": enrolled["device_id"], "tool": "get_system_info", "args": {}},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    claimed = client.get(
        "/api/agent/tasks/next?wait=0",
        headers={"X-Device-Token": enrolled["device_token"]},
    ).json()
    assert claimed["task"]["id"] == task["task_id"]
    return task["task_id"], enrolled["device_token"]


def test_cancelled_task_rejects_late_success(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "control.db"))
    task_id, device_token = _running_task(client)
    cancelled = client.post(f"/api/tasks/{task_id}/cancel", headers={"X-Admin-Token": ADMIN})
    assert cancelled.status_code == 200

    late = client.post(
        f"/api/agent/tasks/{task_id}/result",
        json={"status": "completed", "result": "late completion"},
        headers={"X-Device-Token": device_token},
    )
    assert late.status_code == 409


def test_dependency_blocks_until_parent_completes_and_records_events(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "dependencies.db"))
    parent_id, device_token = _running_task(client)
    device_id = client.get("/api/devices", headers={"X-Admin-Token": ADMIN}).json()[0]["id"]
    child = client.post(
        "/api/tasks",
        json={"device_id": device_id, "tool": "get_system_info", "depends_on": [parent_id]},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    assert client.get("/api/agent/tasks/next", headers={"X-Device-Token": device_token}).json()["task"] is None

    saved = client.put(
        f"/api/agent/tasks/{parent_id}/checkpoint",
        json={"checkpoint": {"step": 2, "secret": "token=example"}},
        headers={"X-Device-Token": device_token},
    )
    assert saved.status_code == 200
    finished = client.post(
        f"/api/agent/tasks/{parent_id}/result",
        json={"status": "completed", "result": "ok"},
        headers={"X-Device-Token": device_token},
    )
    assert finished.status_code == 200
    claimed = client.get("/api/agent/tasks/next", headers={"X-Device-Token": device_token}).json()["task"]
    assert claimed["id"] == child["task_id"]
    events = client.get(f"/api/tasks/{parent_id}/events", headers={"X-Admin-Token": ADMIN}).json()
    assert [event["event_type"] for event in events] == ["created", "running", "checkpoint_saved", "completed"]


def test_dependency_fails_when_parent_is_cancelled(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "dependency-failure.db"))
    parent_id, _device_token = _running_task(client)
    device_id = client.get("/api/devices", headers={"X-Admin-Token": ADMIN}).json()[0]["id"]
    child = client.post(
        "/api/tasks",
        json={"device_id": device_id, "tool": "get_system_info", "depends_on": [parent_id]},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    client.post(f"/api/tasks/{parent_id}/cancel", headers={"X-Admin-Token": ADMIN})
    child_state = client.get(f"/api/tasks/{child['task_id']}", headers={"X-Admin-Token": ADMIN}).json()
    assert child_state["status"] == "failed"


def test_deleting_dependency_parent_fails_waiting_children(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "dependency-delete.db"))
    parent_id, _device_token = _running_task(client)
    device_id = client.get("/api/devices", headers={"X-Admin-Token": ADMIN}).json()[0]["id"]
    child = client.post(
        "/api/tasks",
        json={"device_id": device_id, "tool": "get_system_info", "depends_on": [parent_id]},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    removed = client.delete(f"/api/tasks/{parent_id}", headers={"X-Admin-Token": ADMIN})
    assert removed.status_code == 200
    child_state = client.get(f"/api/tasks/{child['task_id']}", headers={"X-Admin-Token": ADMIN}).json()
    assert child_state["status"] == "failed"
    assert client.get("/api/agent/tasks/next", headers={"X-Device-Token": _device_token}).json()["task"] is None


def test_admin_terminal_transition_records_event_and_fails_dependents(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "admin-transition.db"))
    parent_id, _device_token = _running_task(client)
    device_id = client.get("/api/devices", headers={"X-Admin-Token": ADMIN}).json()[0]["id"]
    child = client.post(
        "/api/tasks",
        json={"device_id": device_id, "tool": "get_system_info", "depends_on": [parent_id]},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    changed = client.put(f"/api/tasks/{parent_id}", json={"status": "failed"}, headers={"X-Admin-Token": ADMIN})
    assert changed.status_code == 200
    assert changed.json()["status"] == "failed"
    child_state = client.get(f"/api/tasks/{child['task_id']}", headers={"X-Admin-Token": ADMIN}).json()
    assert child_state["status"] == "failed"
    events = client.get(f"/api/tasks/{parent_id}/events", headers={"X-Admin-Token": ADMIN}).json()
    assert events[-1]["event_type"] == "admin_updated"


def test_emergency_stop_survives_control_plane_restart(tmp_path):
    db_path = tmp_path / "emergency-stop.db"
    first = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    activated = first.post("/api/emergency-stop", headers={"X-Admin-Token": ADMIN})
    assert activated.status_code == 200

    restarted = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    assert restarted.get("/health", headers={"X-Admin-Token": ADMIN}).json()["emergency_stop"] is True
    enrolled = restarted.post(
        "/api/devices/enroll",
        json={"name": "stopped-device", "hostname": "host", "os": "linux"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    rejected = restarted.post(
        "/api/tasks",
        json={"device_id": enrolled["device_id"], "tool": "get_system_info"},
        headers={"X-Admin-Token": ADMIN},
    )
    assert rejected.status_code == 403
    cleared = restarted.post("/api/emergency-stop/clear", headers={"X-Admin-Token": ADMIN})
    assert cleared.status_code == 200
    third = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    assert third.get("/health").json()["emergency_stop"] is False


def test_restart_marks_running_task_for_operator_review(tmp_path):
    db_path = tmp_path / "restart.db"
    first = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    task_id, _device_token = _running_task(first)
    second = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    state = second.get(f"/api/tasks/{task_id}", headers={"X-Admin-Token": ADMIN}).json()
    assert state["status"] == "failed"
    assert "inspect effects" in state["result"]
    events = second.get(f"/api/tasks/{task_id}/events", headers={"X-Admin-Token": ADMIN}).json()
    assert events[-1]["event_type"] == "interrupted"


def test_heartbeat_persists_bounded_device_inventory(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "inventory.db"))
    enrolled = client.post(
        "/api/devices/enroll",
        json={"name": "inventory-test", "hostname": "host", "os": "linux"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    heartbeat = client.post(
        "/api/agent/heartbeat",
        json={
            "capabilities": ["screen.capture", "browser", "screen.capture"],
            "inventory": {"installed_apps": ["Editor"], "processes": ["agent"]},
        },
        headers={"X-Device-Token": enrolled["device_token"]},
    )
    assert heartbeat.status_code == 200
    device = client.get("/api/devices", headers={"X-Admin-Token": ADMIN}).json()[0]
    assert device["capabilities"] == ["browser", "screen.capture"]
    assert device["inventory"] == {"installed_apps": ["Editor"], "processes": ["agent"]}
    assert "active_task" in device


def test_duplicate_result_is_idempotent(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "control.db"))
    task_id, device_token = _running_task(client)
    path = f"/api/agent/tasks/{task_id}/result"
    headers = {"X-Device-Token": device_token}
    first = client.post(path, json={"status": "completed", "result": "original"}, headers=headers)
    duplicate = client.post(path, json={"status": "completed", "result": "replacement"}, headers=headers)
    assert first.status_code == 200
    assert duplicate.status_code == 200 and duplicate.json()["idempotent"] is True
    state = client.get(f"/api/tasks/{task_id}", headers={"X-Admin-Token": ADMIN}).json()
    assert state["result"] == "original"
