"""
WebUI 全局设置

- data/settings.json 保存全局默认值、Worker 上限、LLM/在线题库/通知和存储位置
- 首次启动时可以从源 CLI 的 config.yml 只读导入一次（源文件永不写回）
- 对外 API 只返回敏感值的“是否已配置”，不返回明文
"""

import copy
import json
import os
import threading

from . import paths
from .store import SettingsStore

# 设置在主数据库中的键名
SETTINGS_KEY = "global"

# 敏感字段：API 只返回是否存在，不返回值
SECRET_PATHS = (
    "llm.api_key",
    "tiku.enncy-token",
    "tiku.icodef-token",
    "tiku.datam-token",
    "notification.server_chan.sendkey",
    "notification.bark.key",
    "notification.telegram.bot_token",
)

# 仅本机运行：监听地址固定为回环地址，不接受局域网访问
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

DEFAULT_SETTINGS = {
    "server": {
        "host": "127.0.0.1",
        "port": 8848,
    },
    "scheduler": {
        "max_active_workers": 8,
        "stop_grace_seconds": 25,
    },
    "defaults": {
        "video": {
            "mode": "hybrid",
            "max_workers": 8,
            "random_progress": True,
        },
        "answer": {
            "mode": "ai",
            "fallback_to_tiku": True,
            "no_answer_action": "skip",
            "submit_delay": 2,
            "auto_submit": True,
        },
        "learn_count": {
            "times": 10,
            "dwell": 30,
        },
        "download": {
            "path": "data/downloads",
            "scope": "all",
            "chapters": [],
        },
        # 一键完成课程任务点：只处理章节任务点。
        # 独立作业属于独立功能（independent_homework），需单独创建任务。
        "course_all": {},
    },
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.1,
        "max_tokens": 4096,
        "timeout": 180,
    },
    "tiku": {
        "enabled": True,
        "timeout": 10,
        "order": ["enncy", "icodef", "datam"],
        "enncy-token": "",
        "icodef-token": "",
        "datam-token": "",
    },
    "question_bank": {
        "enabled": True,
        "auto_save": True,
    },
    "notification": {
        "enabled": False,
        "server_chan": {"enabled": False, "sendkey": ""},
        "bark": {"enabled": False, "key": "", "server": "https://api.day.app"},
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
    },
    "advanced": {
        "request_delay": 1.0,
        "request_delay_jitter": 0.5,
        "max_retries": 3,
        "retry_delay": 5,
        "learn_count_dwell": 30,
        "rotate_ua": True,
        "log_level": "INFO",
    },
    "storage": {
        "download_dir": "data/downloads",
        "log_retention_days": 7,
    },
}

# 可重入锁：load()/save() 会互相调用，普通 Lock 会自锁
_lock = threading.RLock()
_cache = None
_storage = None


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _set_path(data: dict, key_path: str, value):
    keys = key_path.split(".")
    target = data
    for key in keys[:-1]:
        if not isinstance(target.get(key), dict):
            target[key] = {}
        target = target[key]
    target[keys[-1]] = value


def _get_path(data: dict, key_path: str, default=None):
    value = data
    for key in key_path.split("."):
        if not isinstance(value, dict):
            return default
        value = value.get(key)
        if value is None:
            return default
    return value


def _clamp(value, minimum, maximum, fallback):
    try:
        number = type(fallback)(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(number, maximum))


def normalize(data) -> dict:
    """
    校正关键字段，避免非法配置在运行期深处才爆发

    容错：配置文件损坏（例如被写成数组或字符串）时回退到默认值，
    而不是让整个服务启动失败。
    """
    if not isinstance(data, dict):
        data = {}
    data = _deep_merge(copy.deepcopy(DEFAULT_SETTINGS), data)
    scheduler = data["scheduler"]
    scheduler["max_active_workers"] = _clamp(scheduler.get("max_active_workers"), 1, 20, 8)
    scheduler["stop_grace_seconds"] = _clamp(scheduler.get("stop_grace_seconds"), 3, 300, 25)
    data["server"]["port"] = _clamp(data["server"].get("port"), 1, 65535, 8848)
    # 只允许回环地址：即使配置被人为改成 0.0.0.0 也强制收回本机
    host = str(data["server"].get("host") or "").strip()
    data["server"]["host"] = host if host in LOOPBACK_HOSTS else "127.0.0.1"

    defaults = data["defaults"]
    if defaults["video"].get("mode") not in {"instant", "real_time", "hybrid"}:
        defaults["video"]["mode"] = "hybrid"
    defaults["video"]["max_workers"] = _clamp(defaults["video"].get("max_workers"), 0, 200, 8)
    if defaults["answer"].get("mode") not in {"ai", "tiku", "manual"}:
        defaults["answer"]["mode"] = "ai"
    if defaults["answer"].get("no_answer_action") not in {"skip", "random"}:
        defaults["answer"]["no_answer_action"] = "skip"
    defaults["answer"]["submit_delay"] = _clamp(defaults["answer"].get("submit_delay"), 0, 600, 2)
    defaults["learn_count"]["times"] = _clamp(defaults["learn_count"].get("times"), 1, 9999, 10)
    defaults["learn_count"]["dwell"] = _clamp(defaults["learn_count"].get("dwell"), 0, 3600, 30)
    if defaults["download"].get("scope") not in {"all", "chapters"}:
        defaults["download"]["scope"] = "all"
    if not isinstance(defaults["download"].get("chapters"), list):
        defaults["download"]["chapters"] = []

    data["advanced"]["request_delay"] = _clamp(data["advanced"].get("request_delay"), 0, 60, 1.0)
    data["advanced"]["max_retries"] = _clamp(data["advanced"].get("max_retries"), 0, 10, 3)
    return data


def _read_source_config() -> dict:
    """只读解析源 CLI 的 config.yml（源文件永不写回）"""
    if not os.path.exists(paths.SOURCE_CONFIG):
        return {}
    try:
        import yaml
        with open(paths.SOURCE_CONFIG, "r", encoding="utf-8") as f:
            legacy = yaml.safe_load(f) or {}
    except Exception:
        return {}
    return legacy if isinstance(legacy, dict) else {}


# 源配置文件 -> WebUI 设置的字段映射
_SOURCE_MAPPING = {
    "video": "defaults.video",
    "answer": "defaults.answer",
    "llm": "llm",
    "tiku": "tiku",
    "notification": "notification",
}
_SOURCE_ADVANCED_KEYS = ("request_delay", "request_delay_jitter", "max_retries",
                         "retry_delay", "learn_count_dwell", "rotate_ua", "log_level")


def _apply_source_config(data: dict, legacy: dict, only_empty: bool = False) -> list:
    """
    把源 CLI 配置合并进设置字典

    only_empty=True（默认）时，只有当本地值仍等于 WebUI 默认值（即用户没改过）
    才用源配置填充；这样既能补齐 LLM Key、题库 Token 等空缺，
    又不会覆盖用户在设置页里手动修改过的值。
    返回实际生效的字段路径列表。
    """
    applied = []

    def assign(target_path: str, value):
        if value is None or value == "":
            return
        current = _get_path(data, target_path)
        if current == value:
            return  # 值已一致，无需变更（保证重复导入是幂等的）
        if only_empty:
            default_value = _get_path(DEFAULT_SETTINGS, target_path)
            if current != default_value:
                return  # 用户已自定义，保持本地值
        _set_path(data, target_path, value)
        applied.append(target_path)

    for source_key, target_root in _SOURCE_MAPPING.items():
        section = legacy.get(source_key)
        if not isinstance(section, dict):
            continue
        for key, value in section.items():
            if key == "db_path":
                continue  # 题库路径由 WebUI 自己管理
            if key == "enabled" and source_key == "tiku":
                continue
            assign(f"{target_root}.{key}", value)

    advanced = legacy.get("advanced")
    if isinstance(advanced, dict):
        for key in _SOURCE_ADVANCED_KEYS:
            if key in advanced:
                assign(f"advanced.{key}", advanced[key])

    if not data["defaults"]["video"].get("max_workers"):
        data["defaults"]["video"]["max_workers"] = 8
    # CLI 的 0 线程代表不限制，WebUI 默认值保留原意但限制在 0-200
    data["defaults"]["video"]["max_workers"] = _clamp(
        data["defaults"]["video"].get("max_workers"), 0, 200, 8
    )
    return applied


def source_config_info() -> dict:
    """源配置可用性（界面用于显示可导入项）"""
    legacy = _read_source_config()
    llm = legacy.get("llm", {}) if isinstance(legacy.get("llm"), dict) else {}
    tiku = legacy.get("tiku", {}) if isinstance(legacy.get("tiku"), dict) else {}
    return {
        "exists": bool(legacy),
        "path": paths.SOURCE_CONFIG,
        "has_llm_key": bool(str(llm.get("api_key", "")).strip()),
        "llm_model": llm.get("model", ""),
        "llm_base_url": llm.get("base_url", ""),
        "has_tiku_token": any(str(tiku.get(f"{name}-token", "")).strip()
                              for name in ("enncy", "icodef", "datam")),
        "has_notification": bool(legacy.get("notification", {}).get("enabled")),
    }


def import_from_source_config(only_empty: bool = True) -> dict:
    """
    从源 CLI 的 config.yml 导入 LLM / 题库 / 通知 / 请求参数并持久化到本地数据库

    only_empty=True（默认）只填充本地未自定义的字段，不覆盖用户在 WebUI 里保存的设置。
    """
    legacy = _read_source_config()
    if not legacy:
        return {"imported": False, "reason": "未找到源 CLI 的配置文件", "applied": []}

    global _cache
    with _lock:
        current = _cache if _cache is not None else load()
        merged = copy.deepcopy(current)
        applied = _apply_source_config(merged, legacy, only_empty=only_empty)
        if not applied:
            return {"imported": False, "reason": "没有需要导入的字段（本地均已配置）",
                    "applied": []}
        merged = normalize(merged)
        _persist(merged)
        _cache = merged
    return {"imported": True, "applied": applied, "count": len(applied)}


def _store() -> SettingsStore:
    """惰性创建设置存储（放在 webui.db 里，与任务数据同一文件）"""
    global _storage
    with _lock:
        if _storage is None:
            _storage = SettingsStore()
        return _storage


def _migrate_from_json_once():
    """
    一次性迁移：把历史 data/settings.json 导入数据库

    迁移成功后把原文件改名为 settings.json.migrated 作为备份，
    避免之后两台“真相来源”互相覆盖。
    """
    if not os.path.exists(paths.SETTINGS_FILE):
        return
    try:
        with open(paths.SETTINGS_FILE, "r", encoding="utf-8") as f:
            legacy = json.load(f)
    except (OSError, ValueError):
        legacy = None
    if isinstance(legacy, dict) and legacy:
        _store().set(SETTINGS_KEY, normalize(legacy))
    try:
        os.replace(paths.SETTINGS_FILE, paths.SETTINGS_FILE + ".migrated")
    except OSError:
        pass


def ensure_initialized():
    """
    首次启动写默认值

    源 CLI 配置的导入由服务启动时调用 import_from_source_config(only_empty=True) 完成，
    这样“导入”接口报告的结果始终反映真实发生的变更。
    """
    store = _store()
    if store.has(SETTINGS_KEY):
        return
    _migrate_from_json_once()
    if not store.has(SETTINGS_KEY):
        store.set(SETTINGS_KEY, copy.deepcopy(DEFAULT_SETTINGS))


def _persist(data: dict):
    """写入数据库，同时留一份 JSON 备份便于人工查看"""
    _store().set(SETTINGS_KEY, data)
    try:
        tmp = paths.SETTINGS_BACKUP_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.SETTINGS_BACKUP_FILE)
    except OSError:
        pass  # 备份失败不影响主存储


def load() -> dict:
    """读取全局设置（带内存缓存）"""
    global _cache
    with _lock:
        if _cache is None:
            ensure_initialized()
            raw = _store().get(SETTINGS_KEY, {})
            _cache = normalize(raw)
        return copy.deepcopy(_cache)


def save(updates: dict) -> dict:
    """更新设置：局部合并后规范化并持久化"""
    global _cache
    with _lock:
        current = _cache if _cache is not None else load()
        merged = _deep_merge(copy.deepcopy(current), updates or {})
        merged = normalize(merged)
        _persist(merged)
        _cache = merged
        return copy.deepcopy(_cache)


def storage_info() -> dict:
    """存储位置信息（界面展示用）"""
    return {
        "backend": "sqlite",
        "database": paths.DATABASE_FILE,
        "table": "app_settings",
        "backup": paths.SETTINGS_BACKUP_FILE,
        "host_mode": "local-only",
    }


def export_json() -> str:
    """导出设置 JSON（用于备份/迁移）"""
    return json.dumps(load(), ensure_ascii=False, indent=2)


def import_json(content: str) -> dict:
    """导入设置 JSON（局部合并，不删除未提交的字段）"""
    try:
        payload = json.loads(content)
    except ValueError as exc:
        raise ValueError(f"JSON 解析失败: {exc}")
    if not isinstance(payload, dict):
        raise ValueError("设置 JSON 应为对象")
    return save(payload)


def resolve(key_path: str, default=None):
    return _get_path(load(), key_path, default)


def masked() -> dict:
    """返回给前端的设置：敏感字段替换为 has_* 标记"""
    data = load()
    for secret_path in SECRET_PATHS:
        value = _get_path(data, secret_path, "")
        _set_path(data, secret_path, "")
        flag = secret_path.replace(".", "_").replace("-", "_") + "_configured"
        data.setdefault("secrets", {})[flag] = bool(str(value).strip())
    return data


def apply_updates(payload: dict) -> dict:
    """
    应用前端提交的设置

    规则：
    - 只处理提交里出现的字段，未提交的字段保持原值（局部合并）
    - 敏感字段提交空值或未提交时，保留已保存的密钥，避免回显空值把密钥清掉
    """
    updates = copy.deepcopy(payload or {})
    updates.pop("secrets", None)

    data = load()
    for secret_path in SECRET_PATHS:
        # 必须用嵌套路径取值判断：updates 是 {"llm": {"api_key": ...}} 这样的结构，
        # 用 "llm.api_key" in updates 判断会永远为 False，从而把用户提交的新密钥
        # 覆盖回旧值（表现为“设置页保存不了 API Key”）。
        submitted = _get_path(updates, secret_path, None)
        if submitted is not None and str(submitted).strip() != "":
            continue  # 用户提交了非空值，按提交值保存
        group = secret_path.split(".")[0]
        if group in updates:
            # 只在该分组确实被提交时才回填旧值，避免凭空创建空分组
            _set_path(updates, secret_path, _get_path(data, secret_path, ""))
    return save(updates)
