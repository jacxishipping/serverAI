from __future__ import annotations

import socket

import pytest
from fastapi import HTTPException

from ai_bridge.control import app as control_app


def _dns_answers(*addresses: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]


def test_webhook_host_with_private_dns_answer_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control_app.socket, "getaddrinfo", lambda *args, **kwargs: _dns_answers("93.184.216.34", "10.0.0.8"))
    with pytest.raises(HTTPException, match="non-public"):
        control_app._validate_webhook_url("https://hooks.example.test/path")


def test_webhook_host_with_public_dns_answers_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(control_app.socket, "getaddrinfo", lambda *args, **kwargs: _dns_answers("93.184.216.34"))
    control_app._validate_webhook_url("https://hooks.example.test/path")


@pytest.mark.parametrize("url", ["http://hooks.example.test/path", "https://user:pass@example.test/path"])
def test_webhook_requires_https_without_embedded_credentials(url: str) -> None:
    with pytest.raises(HTTPException):
        control_app._validate_webhook_url(url)
