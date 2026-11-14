from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from ai_bridge.control.app import create_app

ADMIN = "task-concurrency-test-token"


def test_ten_independent_tasks_are_claimed_once(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "concurrency.db"))
    devices = []
    for index in range(10):
        enrolled = client.post(
            "/api/devices/enroll",
            json={"name": f"worker-{index}", "hostname": f"worker-{index}", "os": "linux"},
            headers={"X-Admin-Token": ADMIN},
        ).json()
        devices.append(enrolled)

    def submit(index: int) -> tuple[int, str]:
        response = client.post(
            "/api/tasks",
            json={"device_id": devices[index]["device_id"], "tool": "get_system_info"},
            headers={"X-Admin-Token": ADMIN},
        )
        assert response.status_code == 200
        return index, response.json()["task_id"]

    with ThreadPoolExecutor(max_workers=10) as executor:
        submitted = dict(executor.map(submit, range(10)))

    def claim(index: int) -> tuple[int, str | None]:
        response = client.get(
            "/api/agent/tasks/next?wait=0",
            headers={"X-Device-Token": devices[index]["device_token"]},
        )
        assert response.status_code == 200
        task = response.json()["task"]
        return index, task["id"] if task else None

    with ThreadPoolExecutor(max_workers=10) as executor:
        claimed = dict(executor.map(claim, range(10)))

    assert claimed == submitted
    assert len(set(claimed.values())) == 10
