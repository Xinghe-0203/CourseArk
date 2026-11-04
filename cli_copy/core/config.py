"""
AutoChaoxingCLI - 配置管理模块（v2.4.0 T2 配置单源化）

配置的唯一真相源是 app 层 settings：任务快照经 worker/common.build_base_config
生成后注入 Config。本模块退化为纯内存 schema：
- 不再读写 config.yml（config.yml 子系统在 WebUI 链路是死路，
  且 Config._config_path 曾被指到 *.json 而 save() 用 yaml 写盘，属隐患）。
- data()/get()/set() 语义不变，调用方无需改动。
"""

from typing import Any


class Config:
    """
    全局配置管理器（单例模式，纯内存）

    通过类变量 _data 存储全局配置字典，所有模块通过 Config.data 访问配置。
    """

    _data: dict = None

    @classmethod
    def data(cls) -> dict:
        """获取配置数据（未注入时返回内存默认值，不再触碰文件系统）"""
        if cls._data is None:
            cls.set_defaults({})
        return cls._data

    @classmethod
    def set_defaults(cls, overrides: dict = None) -> dict:
        """
        以内存默认配置为底、深度合并 overrides 后作为当前配置。

        Args:
            overrides: 覆盖项（深度合并，override 优先）

        Returns:
            dict: 规范化后的配置字典
        """
        merged = cls._deep_merge(cls._default_config(), overrides or {})
        cls._data = cls._normalize_config(merged)
        return cls._data

    @classmethod
    def get(cls, key_path: str, default: Any = None) -> Any:
        """
        通过点号路径获取配置值

        Args:
            key_path: 点号分隔的配置路径，如 "video.max_workers"
            default: 默认值

        Returns:
            配置值
        """
        data = cls.data()
        if data is None:
            return default
        keys = key_path.split(".")
        value = data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
            if value is None:
                return default
        return value

    @classmethod
    def set(cls, key_path: str, value: Any):
        """
        通过点号路径设置配置值

        Args:
            key_path: 点号分隔的配置路径
            value: 配置值
        """
        data = cls.data()
        if data is None:
            return
        keys = key_path.split(".")
        target = data
        for key in keys[:-1]:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
            target = target[key]
        target[keys[-1]] = value

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并两个字典，override中的值优先"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Config._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    @staticmethod
    def _normalize_config(data: dict) -> dict:
        """校验并规范化关键配置，避免类型错误在运行中深处才爆发。"""
        defaults = Config._default_config()

        for section, default_value in defaults.items():
            if isinstance(default_value, dict) and not isinstance(data.get(section), dict):
                data[section] = default_value.copy()

        def number(section: str, key: str, cast, minimum, maximum=None):
            raw = data[section].get(key, defaults[section][key])
            try:
                value = cast(raw)
            except (TypeError, ValueError):
                value = defaults[section][key]
            value = max(minimum, value)
            if maximum is not None:
                value = min(maximum, value)
            data[section][key] = value

        number("video", "max_workers", int, 0, 200)
        number("answer", "submit_delay", float, 0)
        number("llm", "temperature", float, 0, 2)
        number("llm", "max_tokens", int, 0)
        number("llm", "timeout", int, 1)
        number("advanced", "request_delay", float, 0)
        number("advanced", "request_delay_jitter", float, 0)
        number("advanced", "max_retries", int, 0, 10)
        number("advanced", "retry_delay", float, 0)
        number("advanced", "learn_count_dwell", float, 0)

        if data["video"].get("mode") not in {"instant", "real_time", "hybrid"}:
            data["video"]["mode"] = defaults["video"]["mode"]
        if data["answer"].get("mode") not in {"ai", "manual"}:
            data["answer"]["mode"] = defaults["answer"]["mode"]
        if data["answer"].get("no_answer_action") not in {"skip", "random"}:
            data["answer"]["no_answer_action"] = defaults["answer"]["no_answer_action"]
        return data

    @staticmethod
    def _default_config() -> dict:
        """生成默认配置（v2.4.0：删 account.phone/password 与
        advanced.log_level/log_file 死键——凭据走任务快照的
        task["username"]/task["password"]，日志级别经 T11 全链路下发）"""
        return {
            "video": {
                "max_workers": 8,
                "mode": "hybrid",
                "random_progress": True,
            },
            "answer": {
                "mode": "ai",
                "no_answer_action": "skip",
                "submit_delay": 2,
                "auto_submit": True,
            },
            "llm": {
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "",
                "model": "deepseek-chat",
                "temperature": 0.1,
                "max_tokens": 4096,
                "timeout": 180,
            },
            "question_bank": {
                "enabled": True,
                "db_path": "data/question_bank.db",
                "auto_save": True,
            },
            "advanced": {
                "request_delay": 1.0,
                "request_delay_jitter": 0.5,
                "max_retries": 3,
                "retry_delay": 5,
                "learn_count_dwell": 30,
                "rotate_ua": True,
            },
        }
