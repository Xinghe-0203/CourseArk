"""Lifecycle hooks required by the Electron shell."""

import subprocess
import sys
import threading
from types import SimpleNamespace


def test_run_host_override_preserves_loopback_only():
    from run import resolve_host

    assert resolve_host("127.0.0.1") == "127.0.0.1"
    assert resolve_host("::1") == "::1"
    assert resolve_host("0.0.0.0") == "127.0.0.1"


class _ShutdownServer:
    should_exit = False


class _Process:
    def __init__(self, exit_on_terminate):
        self.exit_on_terminate = exit_on_terminate
        self.terminated = False
        self.killed = False
        self.wait_calls = []

    def poll(self):
        return -9 if self.killed else (-15 if self.terminated and self.exit_on_terminate else None)

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.killed:
            return -9
        if self.exit_on_terminate:
            return -15
        raise subprocess.TimeoutExpired("worker", timeout)


def test_shutdown_requires_configured_token(app_client, monkeypatch):
    app_client.app.state.uvicorn_server = _ShutdownServer()
    monkeypatch.delenv("AUTOCXWEBUI_SHUTDOWN_TOKEN", raising=False)

    absent = app_client.post("/api/internal/shutdown")
    assert absent.status_code == 404
    assert app_client.app.state.uvicorn_server.should_exit is False

    monkeypatch.setenv("AUTOCXWEBUI_SHUTDOWN_TOKEN", "test-secret")
    denied = app_client.post("/api/internal/shutdown", headers={
        "X-AutoCx-Shutdown-Token": "wrong",
    })
    accepted = app_client.post("/api/internal/shutdown", headers={
        "X-AutoCx-Shutdown-Token": "test-secret",
    })

    assert denied.status_code == 403
    assert accepted.status_code == 202
    assert app_client.app.state.uvicorn_server.should_exit is True


def test_sync_shutdown_terminates_and_kills_stuck_workers(monkeypatch):
    from app import sync_service

    process = _Process(exit_on_terminate=False)
    monkeypatch.setitem(sync_service._running, "account-test", {"process": process})

    sync_service.shutdown(grace=0.01)

    assert process.terminated is True
    assert process.killed is True
    assert process.wait_calls


def test_session_shutdown_terminates_worker(monkeypatch):
    from app import session_service

    process = _Process(exit_on_terminate=True)
    entry = {"process": process}
    monkeypatch.setitem(session_service._running, "account-test", entry)

    session_service.SessionService().shutdown(grace=0.01)

    assert process.terminated is True
    assert process.killed is False
    assert process.wait_calls


def test_session_shutdown_closes_open_playwright_browser(sandbox, monkeypatch):
    from app import session_service

    class Browser:
        def __init__(self):
            self.closed = False
            self.close_wait = threading.Event()

        def new_context(self, **kwargs):
            return SimpleNamespace(
                add_cookies=lambda cookies: None,
                new_page=lambda: SimpleNamespace(goto=lambda *args, **kw: None),
                wait_for_event=lambda *args, **kwargs: self.close_wait.wait(),
            )

        def is_connected(self):
            return not self.closed

        def close(self):
            self.closed = True
            self.close_wait.set()

    class PlaywrightContext:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    browser = Browser()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=PlaywrightContext, Error=RuntimeError,
    ))
    service = session_service.SessionService()
    service.save("account-browser", [{"name": "sid", "value": "cookie"}])
    monkeypatch.setattr(service, "_launch_browser", lambda _playwright: browser)

    try:
        result = service.open_browser("account-browser", "https://example.com/")
        assert result["opened"] is True
        service.shutdown(grace=1)

        assert browser.closed is True
        assert service._browser_threads == {}
    finally:
        browser.close_wait.set()
