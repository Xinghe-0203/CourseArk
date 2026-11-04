"""v2.4.0 T2：Config 纯内存 schema 的守卫测试（钳制/枚举回退/死键删除）。"""
import sys
import os

import pytest

CLI_COPY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cli_copy")


@pytest.fixture()
def fresh_config(monkeypatch):
    sys.path.insert(0, CLI_COPY)
    from core.config import Config
    monkeypatch.setattr(Config, "_data", None)
    try:
        yield Config
    finally:
        monkeypatch.setattr(Config, "_data", None)


def test_defaults_use_webui_baseline(fresh_config):
    """默认值与 app 层基线一致：video 8/hybrid（修正 CLI 20 漂移），AI 做题。"""
    data = fresh_config.data()
    assert data["video"]["max_workers"] == 8
    assert data["video"]["mode"] == "hybrid"
    assert data["answer"]["mode"] == "ai"
    assert data["llm"]["base_url"] == "https://api.deepseek.com/v1"


def test_removed_keys_stay_removed(fresh_config):
    """account.phone/password 与 advanced.log_level/log_file 死键必须删除："""
    data = fresh_config.data()
    assert "account" not in data
    assert "log_level" not in data["advanced"]
    assert "log_file" not in data["advanced"]


def test_numeric_clamping(fresh_config):
    """越界/坏类型回退到默认或钳制到边界。"""
    fresh_config.set_defaults({
        "video": {"max_workers": 9999},
        "advanced": {"max_retries": "bad", "request_delay": -3},
        "llm": {"temperature": 9},
    })
    data = fresh_config.data()
    assert data["video"]["max_workers"] == 200
    assert data["advanced"]["max_retries"] == 3
    assert data["advanced"]["request_delay"] == 0.0
    assert data["llm"]["temperature"] == 2.0


def test_enum_fallback(fresh_config):
    """非法枚举值回退默认，不抛异常。"""
    fresh_config.set_defaults({"video": {"mode": "turbo"}, "answer": {"mode": "tiku"}})
    data = fresh_config.data()
    assert data["video"]["mode"] == "hybrid"
    assert data["answer"]["mode"] == "ai"


def test_corrupted_sections_replaced_by_defaults(fresh_config):
    """嵌套节被垃圾覆盖时用默认节替换（settings 健壮性同源教训）。"""
    data = fresh_config.set_defaults({"video": "garbage", "answer": None})
    assert isinstance(data["video"], dict)
    assert isinstance(data["answer"], dict)
    assert data["video"]["mode"] == "hybrid"


def test_get_set_dot_paths(fresh_config):
    fresh_config.data()
    fresh_config.set("video.max_workers", 4)
    assert fresh_config.get("video.max_workers") == 4
    assert fresh_config.get("video.missing", "fallback") == "fallback"
    assert fresh_config.get("no.such.path", None) is None
