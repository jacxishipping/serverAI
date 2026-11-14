from __future__ import annotations

import json
import time

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ai_bridge.control import app as app_module
from ai_bridge.control import db as dbmod
from ai_bridge.control import mcp_routes
from ai_bridge.control.app import create_app
from ai_bridge.control.secret_store import PREFIX, SecretStoreError, protect_secret, reveal_secret


def test_protect_and_reveal_secret_requires_external_key_when_configured(monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    secret = "provider-secret-value"
    protected = protect_secret(secret)
    assert protected.startswith(PREFIX)
    assert secret not in protected
    assert reveal_secret(protected) == secret

    monkeypatch.setenv("AI_BRIDGE_REQUIRE_SECRET_ENCRYPTION", "1")
    monkeypatch.delenv("AI_BRIDGE_DB_ENCRYPTION_KEY")
    with pytest.raises(SecretStoreError, match="not configured"):
        protect_secret(secret)


def test_database_startup_migrates_legacy_provider_and_mcp_secrets(tmp_path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("AI_BRIDGE_DB_ENCRYPTION_KEY", key)
    db_path = tmp_path / "legacy-secrets.db"
    first = dbmod.connect(db_path=db_path)
    first.execute("INSERT INTO settings (key, value) VALUES (?,?)", ("ai_openai_key", "legacy-api-key"))
    first.execute("INSERT INTO settings (key, value) VALUES (?,?)", ("webhook_url", "https://hooks.example/token"))
    first.execute(
        "INSERT INTO mcp_servers (id, name, url, auth_token, oauth_client_secret, oauth_refresh_token, headers_json, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("mcp-secret", "secret server", "https://mcp.example", "bearer-secret", "client-secret", "refresh-secret", json.dumps({"Authorization": "Bearer header-secret"}), time.time(), time.time()),
    )
    first.commit()
    first.close()

    migrated = dbmod.connect(db_path=db_path)
    values = {
        row["key"]: row["value"]
        for row in migrated.execute("SELECT key, value FROM settings WHERE key IN ('ai_openai_key','webhook_url')").fetchall()
    }
    server = migrated.execute("SELECT * FROM mcp_servers WHERE id='mcp-secret'").fetchone()
    assert all(value.startswith(PREFIX) for value in values.values())
    assert all(value.startswith(PREFIX) for value in (server["auth_token"], server["oauth_client_secret"], server["oauth_refresh_token"], server["headers_json"]))
    assert reveal_secret(values["ai_openai_key"]) == "legacy-api-key"
    assert reveal_secret(values["webhook_url"]) == "https://hooks.example/token"
    assert reveal_secret(server["auth_token"]) == "bearer-secret"
    assert json.loads(reveal_secret(server["headers_json"]))["Authorization"] == "Bearer header-secret"


def test_required_encryption_fails_startup_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_REQUIRE_SECRET_ENCRYPTION", "1")
    monkeypatch.delenv("AI_BRIDGE_DB_ENCRYPTION_KEY", raising=False)
    with pytest.raises(SecretStoreError, match="not set"):
        dbmod.connect(db_path=tmp_path / "secure-required.db")


def test_ai_and_mcp_secret_routes_persist_ciphertext(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_BRIDGE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    app = create_app(admin_token="secret-route-test", db_path=tmp_path / "secret-routes.db")
    client = TestClient(app)
    headers = {"X-Admin-Token": "secret-route-test"}
    monkeypatch.setattr(app_module, "_validate_webhook_url", lambda _url: None)
    webhook_url = "https://hooks.example/super-secret"
    webhook_res = client.post("/api/settings/webhook", headers=headers, json={"webhook_url": webhook_url})
    assert webhook_res.status_code == 200
    webhook_db = app.state.conn.execute("SELECT value FROM settings WHERE key='webhook_url'").fetchone()["value"]
    assert webhook_db.startswith(PREFIX) and webhook_url not in webhook_db
    assert client.get("/api/settings/webhook", headers=headers).json()["webhook_url"] == webhook_url

    alert_payload = {
        "slack_webhook": "https://hooks.example/slack-secret",
        "discord_webhook": "https://hooks.example/discord-secret",
        "telegram_token": "telegram-secret",
        "telegram_chat_id": "42",
        "generic_webhook": "https://hooks.example/generic-secret",
    }
    alert_res = client.put("/api/alerts/config", headers=headers, json=alert_payload)
    assert alert_res.status_code == 200
    alert_db = app.state.conn.execute("SELECT value FROM settings WHERE key='alert_webhooks'").fetchone()["value"]
    assert alert_db.startswith(PREFIX)
    assert client.get("/api/alerts/config", headers=headers).json()["telegram_configured"] is True

    ai_res = client.post(
        "/api/settings/ai",
        headers=headers,
        json={"provider": "openai", "api_key": "api-secret-value", "test_connection": False},
    )
    assert ai_res.status_code == 200
    ai_db = app.state.conn.execute("SELECT value FROM settings WHERE key='ai_openai_key'").fetchone()["value"]
    assert ai_db.startswith(PREFIX) and "api-secret-value" not in ai_db
    assert client.get("/api/settings/ai", headers=headers).json()["keys_configured"]["openai"] is True

    monkeypatch.setattr(mcp_routes, "fetch_mcp_tools", lambda **_kwargs: (True, [], "connected"))
    mcp_res = client.post(
        "/api/mcp/servers",
        headers=headers,
        json={
            "name": "Encrypted connector",
            "url": "https://mcp.example",
            "auth_type": "bearer",
            "auth_token": "mcp-token-value",
            "oauth_client_secret": "oauth-client-secret",
            "headers": {"X-API-Token": "header-token-value"},
        },
    )
    assert mcp_res.status_code == 200
    server_id = mcp_res.json()["server"]["id"]
    row = app.state.conn.execute("SELECT * FROM mcp_servers WHERE id=?", (server_id,)).fetchone()
    assert all(row[key].startswith(PREFIX) for key in ("auth_token", "oauth_client_secret", "headers_json"))
    assert "mcp-token-value" not in mcp_res.text
    assert "header-token-value" not in mcp_res.text
    assert mcp_res.json()["server"]["headers_configured"] is True
