from __future__ import annotations

import time

from fastapi.testclient import TestClient

from ai_bridge.control import oidc
from ai_bridge.control.app import create_app

ADMIN = "persistent-control-state-token"


def test_oidc_state_survives_restart_and_is_consumed_once(tmp_path, monkeypatch):
    db_path = tmp_path / "oidc-pending.db"
    first = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    monkeypatch.setattr(oidc, "oidc_config", lambda: {
        "issuer": "https://identity.example", "client_id": "client", "client_secret": "secret",
        "redirect_uri": "https://control.example/callback", "dashboard_url": "/",
    })
    monkeypatch.setattr(oidc, "discovery", lambda: {"authorization_endpoint": "https://identity.example/authorize"})
    url, state, nonce = oidc.new_login(first.app.state.conn)
    assert state in url

    restarted = TestClient(create_app(admin_token=ADMIN, db_path=db_path))
    pending = oidc.pop_pending(restarted.app.state.conn, state)
    assert pending is not None
    assert pending["nonce"] == nonce
    assert oidc.pop_pending(restarted.app.state.conn, state) is None


def test_expired_oidc_state_is_removed(tmp_path):
    client = TestClient(create_app(admin_token=ADMIN, db_path=tmp_path / "oidc-expired.db"))
    client.app.state.conn.execute(
        "INSERT INTO oidc_pending (state, nonce, created_at) VALUES (?,?,?)",
        ("expired-state", "nonce", time.time() - 601),
    )
    client.app.state.conn.commit()
    assert oidc.pop_pending(client.app.state.conn, "expired-state") is None
    assert client.app.state.conn.execute("SELECT state FROM oidc_pending WHERE state='expired-state'").fetchone() is None
