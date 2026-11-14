"""Web browser automation via Playwright for MCP tool integration.

Provides structured web browser control: navigation, element interaction,
screenshots, and JavaScript execution. The browser instance is kept alive
across tool calls for session persistence (cookies, localStorage, page state).

All tools enforce the same policy/approval model as desktop automation.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import ipaddress
import os
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .config import get_settings
from .policy import Policy
from .tools import _check, default_policy

_runtime_local = threading.local()
_runtimes: dict[str, "_BrowserRuntime"] = {}
_runtimes_lock = threading.Lock()


def _host_allowlist() -> set[str]:
    return {host.strip().lower().rstrip(".") for host in os.environ.get("AI_BRIDGE_BROWSER_ALLOWED_HOSTS", "").split(",") if host.strip()}


def validate_browser_url(url: str) -> str:
    """Allow HTTPS to public hosts; private/HTTP destinations require exact admin allowlisting."""
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Malformed browser URL.") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not host or parsed.username or parsed.password:
        raise ValueError("Browser URLs must be absolute http(s) URLs without embedded credentials.")
    allowlisted = host in _host_allowlist()
    if allowlisted:
        return url
    if parsed.scheme.lower() != "https":
        raise PermissionError("HTTP browser destinations require an exact AI_BRIDGE_BROWSER_ALLOWED_HOSTS entry.")
    if port not in (None, 443):
        raise PermissionError("Nonstandard browser ports require an exact AI_BRIDGE_BROWSER_ALLOWED_HOSTS entry.")
    try:
        ip = ipaddress.ip_address(host)
        addresses = [ip]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)]
        except (OSError, ValueError) as exc:
            raise PermissionError("Browser destination could not be resolved safely.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise PermissionError("Browser destinations resolving to non-public IP addresses are blocked.")
    return url


@dataclass
class _BrowserCall:
    fn: Any
    args: tuple
    kwargs: dict
    done: threading.Event
    result: list


class _ExpiredBrowserSession(RuntimeError):
    pass


class _BrowserRuntime:
    """One Playwright owner thread and isolated Chromium context per principal."""
    IDLE_TIMEOUT_SECONDS = 900

    def __init__(self, principal: str) -> None:
        self.principal = principal
        self.calls: queue.Queue[_BrowserCall | None] = queue.Queue()
        self._state_lock = threading.Lock()
        self._closed = False
        self.thread = threading.Thread(target=self._run, name="browser-session", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        _runtime_local.runtime = self
        while True:
            try:
                call = self.calls.get(timeout=self.IDLE_TIMEOUT_SECONDS)
            except queue.Empty:
                with self._state_lock:
                    if not self.calls.empty():
                        continue
                    self._closed = True
                break
            if call is None:
                with self._state_lock:
                    self._closed = True
                break
            try:
                call.result.append((True, call.fn(*call.args, **call.kwargs)))
            except BaseException as exc:
                call.result.append((False, exc))
            finally:
                call.done.set()
        try:
            _close_browser()
        except Exception:
            pass
        with _runtimes_lock:
            if _runtimes.get(self.principal) is self:
                _runtimes.pop(self.principal, None)

    def invoke(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        call = _BrowserCall(fn, args, kwargs, threading.Event(), [])
        with self._state_lock:
            if self._closed:
                raise _ExpiredBrowserSession("Browser session expired while idle.")
            self.calls.put(call)
        if not call.done.wait(timeout=180):
            raise TimeoutError("Browser operation exceeded the 180 second limit.")
        succeeded, result = call.result[0]
        if not succeeded:
            raise result
        return result


def _in_browser_session(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapped(*args: Any, session_id: str | None = None, **kwargs: Any) -> Any:
        # Direct library callers use one process-local identity. MCP wrappers
        # supply a token-derived identity and reject anonymous HTTP requests.
        principal = session_id or f"local:{os.getpid()}"
        for _ in range(2):
            with _runtimes_lock:
                runtime = _runtimes.get(principal)
                if runtime is None or not runtime.thread.is_alive():
                    runtime = _BrowserRuntime(principal)
                    _runtimes[principal] = runtime
            try:
                return runtime.invoke(fn, *args, **kwargs)
            except _ExpiredBrowserSession:
                with _runtimes_lock:
                    if _runtimes.get(principal) is runtime:
                        _runtimes.pop(principal, None)
        raise RuntimeError("Could not create a live browser session.")
    return wrapped


def _ensure_browser(headless: bool = True) -> Any:
    """Create/reuse the isolated Playwright context owned by this worker thread."""
    runtime = getattr(_runtime_local, "runtime", None)
    if runtime is None:
        raise RuntimeError("Browser operations must run inside an owned browser session.")
    state = getattr(_runtime_local, "browser_state", None)
    if state is not None and state.get("page") is not None and not state["page"].is_closed():
        return state["page"]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for browser automation. "
            "Install it with: pip install playwright && playwright install chromium"
        ) from exc

    if state is not None:
        _close_browser()
    pw = sync_playwright().start()
    context_options = {
        "viewport": {"width": 1280, "height": 720},
        "accept_downloads": True,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        ),
    }
    persistent = os.environ.get("AI_BRIDGE_BROWSER_PERSIST_PROFILES", "0") == "1"
    if persistent:
        from pathlib import Path

        profile_id = hashlib.sha256(runtime.principal.encode()).hexdigest()
        profile_dir = get_settings().data_dir / "browser-profiles" / profile_id
        profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(profile_dir.parent, 0o700)
            os.chmod(profile_dir, 0o700)
        except OSError:
            pass
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(profile_dir)), headless=headless, **context_options
        )
        browser = context.browser
    else:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context(**context_options)
    def guard_request(route: Any) -> None:
        request_url = route.request.url
        scheme = urlsplit(request_url).scheme.lower()
        if scheme in {"about", "data", "blob"}:
            route.continue_()
            return
        try:
            validate_browser_url(request_url)
            route.continue_()
        except Exception:
            route.abort("blockedbyclient")

    context.route("**/*", guard_request)
    page = context.pages[0] if context.pages else context.new_page()
    _runtime_local.browser_state = {"pw": pw, "browser": browser, "context": context, "page": page}
    return page


def _close_browser() -> None:
    """Close this principal's browser and release its Playwright resources."""
    state = getattr(_runtime_local, "browser_state", None)
    if state is None:
        return
    if state.get("page") is not None:
        try:
            state["page"].close()
        except Exception:
            pass
    if state.get("context") is not None:
        try:
            state["context"].close()
        except Exception:
            pass
    if state.get("browser") is not None:
        try:
            state["browser"].close()
        except Exception:
            pass
    if state.get("pw") is not None:
        try:
            state["pw"].stop()
        except Exception:
            pass
    _runtime_local.browser_state = None


def _page_info(page) -> dict:
    """Extract current page metadata."""
    return {
        "url": page.url,
        "title": page.title(),
    }


def _screenshot_page(page, full_page: bool = False) -> dict:
    """Capture a screenshot of the current page viewport or full page."""
    shot_bytes = page.screenshot(full_page=full_page, type="jpeg", quality=80)
    b64 = base64.b64encode(shot_bytes).decode("ascii")
    viewport = page.viewport_size or {"width": 0, "height": 0}
    return {
        "available": True,
        "image_base64": b64,
        "mime_type": "image/jpeg",
        "width": viewport.get("width", 0),
        "height": viewport.get("height", 0),
        "full_page": full_page,
    }


# ---------------------------------------------------------------------------
# Browser MCP Tools
# ---------------------------------------------------------------------------

def browser_navigate(
    url: str,
    *,
    wait_until: str = "networkidle",
    timeout: int = 30,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Navigate the browser to a URL.

    url: Target URL (must be http:// or https://).
    wait_until: When to consider navigation complete ('load', 'domcontentloaded', 'networkidle').
    timeout: Maximum seconds to wait for navigation.
    """
    eff_policy = policy or default_policy()
    _check("browser_navigate", approval_granted=approval_granted, policy=eff_policy)
    validate_browser_url(url)
    page = _ensure_browser()
    page.goto(url, wait_until=wait_until, timeout=timeout * 1000)
    return {"ok": True, "action": "browser_navigate", **_page_info(page)}


def browser_screenshot(
    full_page: bool = False,
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Capture a screenshot of the current browser page.

    full_page: When True, captures the entire scrollable page instead of just the viewport.
    """
    eff_policy = policy or default_policy()
    _check("browser_screenshot", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    return {"ok": True, "action": "browser_screenshot", **_screenshot_page(page, full_page=full_page)}


def browser_click(
    selector: str,
    *,
    button: str = "left",
    clicks: int = 1,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Click an element on the current page matching a CSS selector.

    selector: CSS selector (e.g. 'button#submit', '.nav-link').
    button: 'left', 'right', or 'middle'.
    clicks: Number of clicks (1 for single, 2 for double).
    """
    eff_policy = policy or default_policy()
    _check("browser_click", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    el = page.locator(selector).first
    if clicks == 2:
        el.dblclick(button=button)
    else:
        el.click(button=button, click_count=clicks)
    return {"ok": True, "action": "browser_click", "selector": selector, **_page_info(page)}


def browser_type(
    selector: str,
    text: str,
    *,
    clear_first: bool = True,
    submit: bool = False,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Type text into an input element matching a CSS selector.

    selector: CSS selector for the input/textarea element.
    text: Text to type.
    clear_first: Clear existing content before typing.
    submit: Press Enter after typing.
    """
    eff_policy = policy or default_policy()
    _check("browser_type", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    el = page.locator(selector).first
    if clear_first:
        el.fill(text)
    else:
        el.type(text)
    if submit:
        el.press("Enter")
    return {"ok": True, "action": "browser_type", "selector": selector, "text": text, **_page_info(page)}


def browser_get_text(
    selector: str = "body",
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Extract visible text content from elements matching a CSS selector.

    selector: CSS selector (default 'body' for full page text).
    """
    eff_policy = policy or default_policy()
    _check("browser_get_text", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    texts = page.locator(selector).all_inner_texts()
    return {
        "ok": True,
        "action": "browser_get_text",
        "selector": selector,
        "count": len(texts),
        "texts": texts,
        **_page_info(page),
    }


def browser_evaluate(
    script: str,
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Execute JavaScript in the current page context and return the result.

    script: JavaScript code to execute. Use 'return' to yield a value.
    """
    eff_policy = policy or default_policy()
    _check("browser_evaluate", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    result = page.evaluate(script)
    # Serialize safely
    try:
        serialized = result if isinstance(result, (str, int, float, bool, type(None))) else str(result)
    except Exception:
        serialized = str(result)
    return {
        "ok": True,
        "action": "browser_evaluate",
        "result": serialized,
        **_page_info(page),
    }


def browser_get_url(
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Return the current page URL and title."""
    eff_policy = policy or default_policy()
    _check("browser_get_url", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    return {"ok": True, "action": "browser_get_url", **_page_info(page)}


def browser_go_back(
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Navigate back in browser history."""
    eff_policy = policy or default_policy()
    _check("browser_go_back", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    page.go_back()
    return {"ok": True, "action": "browser_go_back", **_page_info(page)}


def browser_go_forward(
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Navigate forward in browser history."""
    eff_policy = policy or default_policy()
    _check("browser_go_forward", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    page.go_forward()
    return {"ok": True, "action": "browser_go_forward", **_page_info(page)}


def browser_scroll(
    delta_y: int = 0,
    delta_x: int = 0,
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Scroll the current page by delta pixels.

    delta_y: Vertical scroll amount (positive = down, negative = up).
    delta_x: Horizontal scroll amount (positive = right, negative = left).
    """
    eff_policy = policy or default_policy()
    _check("browser_scroll", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    page.evaluate(f"window.scrollBy({delta_x}, {delta_y})")
    return {"ok": True, "action": "browser_scroll", "delta_x": delta_x, "delta_y": delta_y, **_page_info(page)}


def browser_close(
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Close the browser and release all resources."""
    eff_policy = policy or default_policy()
    _check("browser_close", approval_granted=approval_granted, policy=eff_policy)
    _close_browser()
    return {"ok": True, "action": "browser_close", "note": "Browser closed."}


def browser_new_page(
    url: str | None = None,
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Open a new browser tab. Optionally navigate to a URL.

    url: Optional URL to navigate the new tab to.
    """
    eff_policy = policy or default_policy()
    _check("browser_new_page", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    new_page = page.context.new_page()
    _runtime_local.browser_state["page"] = new_page
    if url:
        validate_browser_url(url)
        new_page.goto(url)
    return {"ok": True, "action": "browser_new_page", **_page_info(new_page)}


def browser_get_elements(
    selector: str,
    *,
    include_text: bool = True,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """List elements matching a CSS selector with tag names, counts, and optional text snippets.

    selector: CSS selector to query.
    include_text: Include visible text for each matched element.
    """
    eff_policy = policy or default_policy()
    _check("browser_get_elements", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    loc = page.locator(selector)
    count = loc.count()
    elements: list[dict] = []
    for i in range(min(count, 50)):
        el = loc.nth(i)
        tag = el.evaluate("el => el.tagName.toLowerCase()")
        info: dict[str, Any] = {"index": i, "tag": tag}
        if include_text:
            try:
                info["text"] = el.inner_text()[:200]
            except Exception:
                info["text"] = ""
        try:
            info["id"] = el.get_attribute("id") or ""
            info["class"] = el.get_attribute("class") or ""
        except Exception:
            pass
        elements.append(info)
    return {
        "ok": True,
        "action": "browser_get_elements",
        "selector": selector,
        "count": count,
        "elements": elements,
        **_page_info(page),
    }


def browser_wait_for_selector(
    selector: str,
    timeout: int = 10,
    *,
    state: str = "visible",
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Wait until an element matching the CSS selector appears (or disappears) on the page.

    selector: CSS selector to wait for.
    timeout: Maximum seconds to wait.
    state: 'visible', 'hidden', 'attached', or 'detached'.
    """
    eff_policy = policy or default_policy()
    _check("browser_wait_for_selector", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    page.locator(selector).first.wait_for(state=state, timeout=timeout * 1000)
    return {
        "ok": True,
        "action": "browser_wait_for_selector",
        "selector": selector,
        "state": state,
        **_page_info(page),
    }


def browser_select_option(
    selector: str,
    value: str | None = None,
    label: str | None = None,
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Select an option in a <select> dropdown by value or visible label.

    selector: CSS selector for the <select> element.
    value: Option value attribute to select.
    label: Visible text of the option to select.
    """
    eff_policy = policy or default_policy()
    _check("browser_select_option", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    el = page.locator(selector).first
    if value is not None:
        el.select_option(value=value)
    elif label is not None:
        el.select_option(label=label)
    else:
        raise ValueError("Either 'value' or 'label' must be provided.")
    return {"ok": True, "action": "browser_select_option", "selector": selector, **_page_info(page)}


def browser_download_file(
    url: str,
    filename: str | None = None,
    *,
    approval_granted: bool = False,
    policy: Policy | None = None,
) -> dict:
    """Download a file via the browser context to the workspace data directory.

    url: Direct URL of the file to download.
    filename: Optional filename override (defaults to URL basename).
    """
    eff_policy = policy or default_policy()
    _check("browser_download_file", approval_granted=approval_granted, policy=eff_policy)
    page = _ensure_browser()
    parsed = urlsplit(validate_browser_url(url))
    requested_name = filename or (parsed.path.rsplit("/", 1)[-1] or "download")
    fname = os.path.basename(requested_name.replace("\\", "/"))
    if fname in {"", ".", ".."} or "\x00" in fname:
        raise ValueError("Download filename must be a plain file name.")
    out_dir = get_settings().data_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / fname
    # Use browser context to download (respects cookies/session)
    with page.expect_download() as download_info:
        page.evaluate("url => { window.location.href = url; }", url)
    download = download_info.value
    download_path = download.path()
    if download_path and os.path.getsize(download_path) > 100 * 1024 * 1024:
        download.cancel()
        raise ValueError("Downloads larger than 100 MiB are blocked.")
    download.save_as(str(out_path))
    return {
        "ok": True,
        "action": "browser_download_file",
        "url": url,
        "path": str(out_path),
        "filename": fname,
        **_page_info(page),
    }


# Every public browser operation executes on the principal's Playwright owner
# thread. That preserves browser persistence without sharing pages or cookies
# across authenticated MCP principals, and avoids cross-thread Playwright use.
for _tool_name, _tool in tuple(globals().items()):
    if _tool_name.startswith("browser_") and callable(_tool):
        globals()[_tool_name] = _in_browser_session(_tool)
