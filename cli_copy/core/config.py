"""
AutoChaoxingCLI - 配置管理模块

负责YAML配置文件的加载、验证、保存和默认值管理。
支持原子写入策略防止配置损坏。
"""

import os
from typing import Any

import yaml
from loguru import logger

from core.paths import get_user_data_path


class Config:
    """
    全局配置管理器（单例模式）

    通过类变量 _data 存储全局配置字典，所有模块通过 Config.data 访问配置。

    Attributes:
        _data (dict): 全局配置数据
        _config_path (str): 配置文件路径
    """
    _data: dict = None
    _config_path: str = "config.yml"

    @classmethod
    def data(cls) -> dict:
        """获取配置数据"""
        if cls._data is None:
            cls.load(cls._config_path)
        return cls._data

    @classmethod
    def load(cls, config_path: str = "config.yml") -> dict:
        """
        加载配置文件

        Args:
            config_path: 配置文件路径

        Returns:
            dict: 配置字典
        """
        # 解析为绝对路径（兼容 PyInstaller 打包）
        if not os.path.isabs(config_path):
            config_path = get_user_data_path(config_path)
        cls._config_path = config_path
        if not os.path.exists(config_path):
            logger.warning(f"配置文件 {config_path} 不存在，使用默认配置")
            cls._data = cls._default_config()
            os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
            cls.save()
            return cls._data

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if not isinstance(loaded, dict):
                logger.error("配置文件内容异常，本次使用内存默认配置，原文件已保留")
                cls._data = cls._default_config()
            else:
                # 合并默认配置（确保新增字段有默认值）
                cls._data = cls._normalize_config(
                    cls._deep_merge(cls._default_config(), loaded)
                )
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}，本次使用内存默认配置，原文件已保留")
            cls._data = cls._default_config()

        return cls._data

    @classmethod
    def save(cls):
        """保存配置到文件（原子写入）"""
        if not isinstance(cls._data, dict):
            logger.error("配置数据异常，拒绝写入")
            return

        tmp_path = cls._config_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(cls._config_path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cls._data, f, allow_unicode=True, sort_keys=False)
            os.replace(tmp_path, cls._config_path)
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

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
                logger.warning(f"配置项 {section} 应为对象，已恢复默认值")
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
        number("tiku", "timeout", int, 1)
        number("advanced", "request_delay", float, 0)
        number("advanced", "request_delay_jitter", float, 0)
        number("advanced", "max_retries", int, 0, 10)
        number("advanced", "retry_delay", float, 0)
        number("advanced", "learn_count_dwell", float, 0)

        if data["video"].get("mode") not in {"instant", "real_time", "hybrid"}:
            data["video"]["mode"] = defaults["video"]["mode"]
        if data["answer"].get("mode") not in {"ai", "tiku", "manual"}:
            data["answer"]["mode"] = defaults["answer"]["mode"]
        if data["answer"].get("no_answer_action") not in {"skip", "random"}:
            data["answer"]["no_answer_action"] = defaults["answer"]["no_answer_action"]
        return data

    @staticmethod
    def _default_config() -> dict:
        """生成默认配置"""
        return {
            "account": {
                "phone": "",
                "password": "",
            },
            "video": {
                "max_workers": 20,
                "mode": "hybrid",
                "random_progress": True,
            },
            "answer": {
                "mode": "ai",
                "fallback_to_tiku": True,
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
            "tiku": {
                "enabled": True,
                "timeout": 10,
            },
            "question_bank": {
                "enabled": True,
                "db_path": "data/question_bank.db",
                "auto_save": True,
            },
            "notification": {
                "enabled": False,
                "server_chan": {
                    "enabled": False,
                    "sendkey": "",
                },
                "bark": {
                    "enabled": False,
                    "key": "",
                    "server": "https://api.day.app",
                },
                "telegram": {
                    "enabled": False,
                    "bot_token": "",
                    "chat_id": "",
                },
            },
            "advanced": {
                "request_delay": 1.0,
                "request_delay_jitter": 0.5,
                "max_retries": 3,
                "retry_delay": 5,
                "learn_count_dwell": 30,
                "rotate_ua": True,
                "log_level": "INFO",
                "log_file": "logs/autochaoxing.log",
            },
        }
