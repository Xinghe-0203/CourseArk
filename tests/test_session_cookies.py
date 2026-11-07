"""T16 应用内验证窗配套的 Cookie 导出/回写接口。

桌面端验证窗注入登录态前读 Cookie，完成人机验证后把窗口会话回写；
两条接口只在本机回环服务上工作，Cookie 不出本机。
"""

import pytest

from app import accounts, session_service


@pytest.fixture()
def account_with_session(sandbox):
    account = accounts.create_account("13800009999", "test-password")
    service = session_service.SessionService()
    service.save(
        account["id"],
        [
            {"name": "fid", "value": "123", "domain": ".chaoxing.com", "path": "/",
             "expires": 1893456000, "secure": True},
            {"name": "_uid", "value": "456", "domain": ".chaoxing.com", "path": "/"},
        ],
        display_name="刘畅",
        uid="456",
    )
    return account


def test_session_cookies_export_requires_account(app_client):
    assert app_client.get("/api/accounts/missing/session/cookies").status_code == 404


def test_session_cookies_export_requires_session(app_client, sandbox):
    account = accounts.create_account("13800008888", "test-password")
    response = app_client.get(f"/api/accounts/{account['id']}/session/cookies")
    assert response.status_code == 409
    assert "获取会话" in response.json()["detail"]


def test_session_cookies_export_roundtrip(app_client, account_with_session):
    response = app_client.get(
        f"/api/accounts/{account_with_session['id']}/session/cookies")
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["name"] for item in items} == {"fid", "_uid"}


def test_session_cookies_import_validates_payload(app_client, account_with_session):
    account_id = account_with_session["id"]
    missing = app_client.post(f"/api/accounts/{account_id}/session/cookies", json={})
    assert missing.status_code == 400
    malformed = app_client.post(
        f"/api/accounts/{account_id}/session/cookies",
        json={"items": [{"value": "no-name"}]},
    )
    assert malformed.status_code == 400


def test_session_cookies_import_writes_back(app_client, account_with_session):
    account_id = account_with_session["id"]
    response = app_client.post(
        f"/api/accounts/{account_id}/session/cookies",
        json={"items": [
            {"name": "vc3", "value": "token-after-captcha",
             "domain": ".chaoxing.com", "path": "/", "expires": 1893456000,
             "secure": True, "httpOnly": True},
            {"name": "route", "value": "session", "domain": ".chaoxing.com",
             "path": "/", "junk": "filtered-out"},
        ]},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 2

    service = session_service.SessionService()
    entry = service.get(account_id)
    names = {item["name"] for item in entry["cookies"]}
    assert names == {"vc3", "route"}
    # 白名单外的字段不落库
    assert all("junk" not in item for item in entry["cookies"])
    assert entry["display_name"] == "刘畅"
    # 登录状态保持 ok（账号列表页徽标不闪红）
    account = accounts.get_account(account_id)
    assert account["login_state"] == "ok"


def test_session_cookies_import_requires_account(app_client):
    response = app_client.post(
        "/api/accounts/missing/session/cookies",
        json={"items": [{"name": "a", "value": "b"}]},
    )
    assert response.status_code == 404
