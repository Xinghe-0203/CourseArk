"""
账号存储（data/accounts.json）

- 明文保存手机号与密码（用户明确的个人本地场景）
- 原子写入：临时文件 + os.replace，避免中途崩溃损坏文件
- 对 API 输出时移除密码字段，只返回 has_password
- 删除账号不会删除历史任务、课程快照或题库内容
"""

import json
import os
import re
import threading
import time
import uuid

from . import paths

DEFAULT_LABEL_PREFIX = "账号"
_lock = threading.RLock()


def _read_raw() -> dict:
    if not os.path.exists(paths.ACCOUNTS_FILE):
        return {"accounts": []}
    try:
        with open(paths.ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {"accounts": []}
    if isinstance(data, list):  # 兼容裸数组形式
        data = {"accounts": data}
    if not isinstance(data, dict):
        return {"accounts": []}
    data.setdefault("accounts", [])
    if not isinstance(data["accounts"], list):
        data["accounts"] = []
    return data


def _write_raw(data: dict):
    os.makedirs(os.path.dirname(paths.ACCOUNTS_FILE), exist_ok=True)
    tmp = paths.ACCOUNTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, paths.ACCOUNTS_FILE)


def mask_username(username: str) -> str:
    """手机号脱敏显示：保留前 3 位和后 4 位"""
    text = str(username or "")
    if len(text) < 7:
        return text
    return f"{text[:3]}****{text[-4:]}"


def mask_password(password: str) -> str:
    return "********" if password else ""


def public_view(account: dict, include_password: bool = False) -> dict:
    """对外视图：默认不含密码，只返回 has_password"""
    view = dict(account)
    password = view.pop("password", "")
    view["has_password"] = bool(password)
    view.setdefault("username", "")
    view["username_masked"] = mask_username(view["username"])
    view.pop("session_cookies", None)
    if include_password:
        view["password"] = password
    return view


def _next_label(accounts: list) -> str:
    used = {acc.get("label", "") for acc in accounts}
    index = 1
    while True:
        label = f"{DEFAULT_LABEL_PREFIX} {index:02d}"
        if label not in used:
            return label
        index += 1


def list_accounts(public: bool = True) -> list:
    with _lock:
        accounts = _read_raw()["accounts"]
    accounts.sort(key=lambda item: item.get("created_at", ""))
    return [public_view(acc) for acc in accounts] if public else accounts


def get_account(account_id: str, public: bool = True):
    for account in list_accounts(public=False):
        if account.get("id") == account_id:
            return public_view(account) if public else account
    return None


def get_account_by_username(username: str):
    target = str(username or "").strip()
    for account in list_accounts(public=False):
        if str(account.get("username", "")).strip() == target:
            return account
    return None


def validate_username(username: str):
    text = str(username or "").strip()
    if not text:
        raise ValueError("手机号不能为空")
    if len(text) < 5:
        raise ValueError("手机号长度不合法")
    return text


def create_account(username: str, password: str, label: str = "", enabled: bool = True) -> dict:
    username = validate_username(username)
    if not password:
        raise ValueError("密码不能为空")
    with _lock:
        data = _read_raw()
        if any(str(acc.get("username", "")).strip() == username for acc in data["accounts"]):
            raise ValueError("该手机号已存在")
        now = _now()
        account = {
            "id": uuid.uuid4().hex,
            "label": str(label or "").strip() or _next_label(data["accounts"]),
            "username": username,
            "password": password,
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
            "login_state": "unknown",
            "last_login_at": None,
            "last_sync_at": None,
            "last_sync_status": "",
            "last_error": "",
            "display_name": "",
        }
        data["accounts"].append(account)
        _write_raw(data)
        return public_view(account)


def update_account(account_id: str, updates: dict) -> dict:
    with _lock:
        data = _read_raw()
        for account in data["accounts"]:
            if account.get("id") != account_id:
                continue
            if "username" in updates and updates["username"]:
                username = validate_username(updates["username"])
                if any(
                    str(other.get("username", "")).strip() == username and other.get("id") != account_id
                    for other in data["accounts"]
                ):
                    raise ValueError("该手机号已存在")
                account["username"] = username
            if "label" in updates and str(updates["label"] or "").strip():
                account["label"] = str(updates["label"]).strip()
            if "enabled" in updates:
                account["enabled"] = bool(updates["enabled"])
            # 密码只允许覆盖，不回显
            if updates.get("password"):
                account["password"] = str(updates["password"])
            account["updated_at"] = _now()
            _write_raw(data)
            return public_view(account)
    raise KeyError("账号不存在")


def delete_account(account_id: str) -> bool:
    with _lock:
        data = _read_raw()
        before = len(data["accounts"])
        data["accounts"] = [acc for acc in data["accounts"] if acc.get("id") != account_id]
        if len(data["accounts"]) == before:
            return False
        _write_raw(data)
        return True


def mark_login(account_id: str, ok: bool, error: str = "", display_name: str = ""):
    _mark(account_id, {
        "login_state": "ok" if ok else "failed",
        "last_login_at": _now(),
        "last_error": "" if ok else str(error)[:500],
        **({"display_name": display_name} if display_name else {}),
    })


def mark_sync(account_id: str, ok: bool, error: str = ""):
    _mark(account_id, {
        "last_sync_at": _now(),
        "last_sync_status": "ok" if ok else "failed",
        "last_error": "" if ok else str(error)[:500],
    })


def _mark(account_id: str, fields: dict):
    with _lock:
        data = _read_raw()
        for account in data["accounts"]:
            if account.get("id") == account_id:
                account.update(fields)
                account["updated_at"] = _now()
                _write_raw(data)
                return public_view(account)
    return None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def summary() -> dict:
    """总览用：账号数、最近在线、登录失败"""
    accounts = list_accounts(public=False)
    online = sum(1 for acc in accounts if acc.get("login_state") == "ok")
    failed = sum(1 for acc in accounts if acc.get("login_state") == "failed")
    return {
        "total": len(accounts),
        "enabled": sum(1 for acc in accounts if acc.get("enabled", True)),
        "online": online,
        "login_failed": failed,
    }


def is_valid_password(password: str) -> bool:
    return bool(str(password or "").strip()) and not re.search(r"\s", str(password))
