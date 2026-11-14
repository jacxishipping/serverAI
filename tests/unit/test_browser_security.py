from __future__ import annotations

import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from ai_bridge import browser_tools, server, webrtc_stream


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:password@example.com/",
        "https://127.0.0.1/",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/",
        "http://example.com/",
        "https://example.com:8443/",
    ],
)
def test_browser_url_rejects_unsafe_destinations(url: str) -> None:
    with pytest.raises((ValueError, PermissionError)):
        browser_tools.validate_browser_url(url)


def test_browser_url_allows_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_BRIDGE_BROWSER_ALLOWED_HOSTS", raising=False)
    answer = [(None, None, None, None, ("93.184.216.34", 443))]
    with patch.object(browser_tools.socket, "getaddrinfo", return_value=answer):
        assert browser_tools.validate_browser_url("https://example.com/path") == "https://example.com/path"


def test_browser_url_blocks_host_with_private_dns_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_BRIDGE_BROWSER_ALLOWED_HOSTS", raising=False)
    answer = [
        (None, None, None, None, ("93.184.216.34", 443)),
        (None, None, None, None, ("10.0.0.8", 443)),
    ]
    with patch.object(browser_tools.socket, "getaddrinfo", return_value=answer):
        with pytest.raises(PermissionError, match="non-public"):
            browser_tools.validate_browser_url("https://mixed-dns.example/")


def test_exact_allowlist_can_enable_private_http_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BRIDGE_BROWSER_ALLOWED_HOSTS", "localhost, 127.0.0.1")
    assert browser_tools.validate_browser_url("http://localhost:8000/") == "http://localhost:8000/"


def test_browser_operations_are_partitioned_by_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeThread:
        @staticmethod
        def is_alive() -> bool:
            return True

    class FakeRuntime:
        def __init__(self, principal: str) -> None:
            self.principal = principal
            self.thread = FakeThread()

        def invoke(self, fn, *args, **kwargs):
            return self.principal, fn(*args, **kwargs)

    runtimes: dict[str, FakeRuntime] = {}

    monkeypatch.setattr(browser_tools, "_runtimes", runtimes)
    monkeypatch.setattr(browser_tools, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(browser_tools, "_runtimes_lock", threading.Lock())

    operation = browser_tools._in_browser_session(lambda value: value)
    assert operation("one", session_id="principal:a") == ("principal:a", "one")
    assert operation("two", session_id="principal:b") == ("principal:b", "two")
    assert operation("again", session_id="principal:a") == ("principal:a", "again")
    assert set(runtimes) == {"principal:a", "principal:b"}


def test_playwright_context_is_created_once_per_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePage:
        url = "about:blank"

        def is_closed(self):
            return False

        def title(self):
            return ""

    class FakeContext:
        def __init__(self):
            self.pages = []
            self.routes = []

        def route(self, pattern, handler):
            self.routes.append((pattern, handler))

        def new_page(self):
            page = FakePage()
            self.pages.append(page)
            return page

        def close(self):
            pass

    class FakeBrowser:
        def __init__(self):
            self.contexts = []

        def new_context(self, **kwargs):
            context = FakeContext()
            self.contexts.append(context)
            contexts.append(context)
            return context

        def close(self):
            pass

    class FakeChromium:
        def launch(self, **kwargs):
            browser = FakeBrowser()
            browsers.append(browser)
            return browser

    class FakePlaywright:
        chromium = FakeChromium()

        def stop(self):
            pass

    browsers = []
    contexts = []
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda: SimpleNamespace(start=lambda: FakePlaywright())
    playwright = ModuleType("playwright")
    playwright.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(browser_tools, "_runtimes", {})

    first = browser_tools.browser_get_url(session_id="principal:a")
    other = browser_tools.browser_get_url(session_id="principal:b")
    again = browser_tools.browser_get_url(session_id="principal:a")
    assert first["ok"] and other["ok"] and again["ok"]
    assert len(browsers) == 2
    assert len(contexts) == 2
    assert contexts[0] is not contexts[1]
    assert all(len(context.routes) == 1 for context in contexts)
    browser_tools.browser_close(session_id="principal:a", approval_granted=True)
    browser_tools.browser_close(session_id="principal:b", approval_granted=True)


def test_idle_browser_runtime_expires_and_is_recreated(monkeypatch: pytest.MonkeyPatch) -> None:
    runtimes: dict[str, object] = {}
    monkeypatch.setattr(browser_tools, "_runtimes", runtimes)
    monkeypatch.setattr(browser_tools._BrowserRuntime, "IDLE_TIMEOUT_SECONDS", 0.02)
    operation = browser_tools._in_browser_session(lambda: threading.current_thread().name)

    first_thread = operation(session_id="principal:idle")
    deadline = time.monotonic() + 1
    while runtimes and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runtimes == {}
    second_thread = operation(session_id="principal:idle")
    assert first_thread == second_thread == "browser-session"


def test_http_browser_identity_is_token_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    request = object()
    context = SimpleNamespace(request_context=SimpleNamespace(request=request))
    monkeypatch.setattr(server.mcp, "get_context", lambda: context)
    monkeypatch.setattr(server, "_bearer_token", lambda: "token-a")
    first = server._browser_principal()
    assert first == server._browser_principal()
    monkeypatch.setattr(server, "_bearer_token", lambda: "token-b")
    assert first != server._browser_principal()


def test_anonymous_http_browser_identity_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    context = SimpleNamespace(request_context=SimpleNamespace(request=object()))
    monkeypatch.setattr(server.mcp, "get_context", lambda: context)
    monkeypatch.setattr(server, "_bearer_token", lambda: None)
    with pytest.raises(PermissionError, match="authenticated bearer"):
        server._browser_principal()


def test_turn_credentials_fail_closed_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_BRIDGE_TURN_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="AI_BRIDGE_TURN_SECRET"):
        webrtc_stream.generate_ephemeral_turn_credentials()
    assert webrtc_stream.get_configured_ice_servers() == webrtc_stream.DEFAULT_ICE_SERVERS
