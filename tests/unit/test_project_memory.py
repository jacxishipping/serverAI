from __future__ import annotations

from fastapi.testclient import TestClient

from ai_bridge.control.app import create_app


ADMIN = "project-memory-test-token"


def test_project_memory_is_provenance_backed_and_tenant_scoped(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "memory.db"))
    enrolled = client.post(
        "/api/devices/enroll",
        json={"name": "memory-test", "hostname": "host", "os": "linux", "tenant": "acme"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"device_id": enrolled["device_id"], "tenant": "acme", "tool": "get_system_info"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    created = client.post(
        "/api/projects/service-api/memory",
        json={
            "tenant": "acme",
            "title": "Runtime baseline",
            "content": "Service uses the staging endpoint.",
            "source": "verified task result",
            "source_task_id": task["task_id"],
            "retention_days": 30,
        },
        headers={"X-Admin-Token": ADMIN},
    )
    assert created.status_code == 200
    memory = created.json()
    assert memory["source_task_id"] == task["task_id"]
    assert memory["expires_at"] > memory["created_at"]
    listed = client.get(
        "/api/projects/service-api/memory?tenant=acme",
        headers={"X-Admin-Token": ADMIN},
    ).json()
    assert [item["id"] for item in listed] == [memory["id"]]
    assert client.get("/api/projects/service-api/memory?tenant=other", headers={"X-Admin-Token": ADMIN}).json() == []
    deleted = client.delete(
        f"/api/projects/service-api/memory/{memory['id']}",
        headers={"X-Admin-Token": ADMIN},
    )
    assert deleted.status_code == 200


def test_project_memory_rejects_source_task_from_another_tenant(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "memory-source.db"))
    enrolled = client.post(
        "/api/devices/enroll",
        json={"name": "memory-source-test", "hostname": "host", "os": "linux"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"device_id": enrolled["device_id"], "tool": "get_system_info"},
        headers={"X-Admin-Token": ADMIN},
    ).json()
    response = client.post(
        "/api/projects/other-project/memory",
        json={"tenant": "other", "title": "Fact", "content": "Evidence", "source": "task", "source_task_id": task["task_id"]},
        headers={"X-Admin-Token": ADMIN},
    )
    assert response.status_code == 404
