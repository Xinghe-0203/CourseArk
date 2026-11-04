"""T1 worker/common.py 公共基座测试（v2.4.0）"""

import os
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker import common  # noqa: E402


# ============================================================
# build_base_config：四 profile 预设
# ============================================================

def _base_job(**extra):
    job = {
        "username": "13800000000",
        "password": "secret",
        "advanced": {},
    }
    job.update(extra)
    return job


def test_task_profile_defaults():
    config = common.build_base_config(_base_job(
        params={"video": {}, "answer": {}, "advanced": {}},
        llm={},
        question_bank_path="q.db",
    ), profile="task")
    # 默认值修正 CLI 漂移：max_workers=8（app settings）而非 CLI 20
    assert config["video"]["max_workers"] == 8
    assert config["video"]["mode"] == "hybrid"
    assert config["video"]["random_progress"] is True
    assert config["answer"]["mode"] == "ai"
    assert config["answer"]["auto_submit"] is True
    assert config["llm"]["base_url"] == "https://api.deepseek.com/v1"
    assert config["llm"]["model"] == "deepseek-chat"
    assert config["llm"]["temperature"] == 0.1
    assert config["question_bank"]["enabled"] is True
    assert config["question_bank"]["db_path"] == "q.db"
    assert config["advanced"]["request_delay"] == 1.0
    assert config["advanced"]["max_retries"] == 3
    assert config["advanced"]["retry_delay"] == 5
    assert config["advanced"]["learn_count_dwell"] == 30
    assert config["advanced"]["rotate_ua"] is True
    assert config["account"]["phone"] == "13800000000"


def test_task_profile_params_override():
    config = common.build_base_config(_base_job(
        params={"video": {"max_workers": 2, "mode": "instant"},
                "answer": {"mode": "manual"},
                "advanced": {"request_delay": 2.5}},
        llm={"model": "custom-model"},
        question_bank_path="q.db",
    ), profile="task")
    assert config["video"]["max_workers"] == 2
    assert config["video"]["mode"] == "instant"
    assert config["answer"]["mode"] == "manual"
    assert config["advanced"]["request_delay"] == 2.5
    assert config["llm"]["model"] == "custom-model"


def test_session_profile_rotate_ua_false():
    """session 的 rotate_ua=False 是有意设计（Cookie/UA 稳定），必须保留"""
    config = common.build_base_config(_base_job(question_bank_path=""), profile="session")
    assert config["advanced"]["rotate_ua"] is False
    assert config["advanced"]["request_delay"] == 0.5
    assert config["advanced"]["request_delay_jitter"] == 0.2
    assert config["advanced"]["max_retries"] == 1
    assert config["advanced"]["retry_delay"] == 2
    assert config["video"] == {"max_workers": 1, "mode": "instant", "random_progress": False}
    assert config["answer"]["mode"] == "manual"
    assert config["llm"]["api_key"] == ""
    assert config["question_bank"]["enabled"] is False
    assert config["advanced"]["learn_count_dwell"] == 0


def test_sync_catalog_profiles():
    for profile in ("sync", "catalog"):
        config = common.build_base_config(_base_job(), profile=profile)
        assert config["advanced"]["request_delay"] == 1.0
        assert config["advanced"]["max_retries"] == 2
        assert config["advanced"]["rotate_ua"] is True
        assert config["question_bank"]["enabled"] is False
        assert config["question_bank"]["db_path"] == ""


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        common.build_base_config(_base_job(), profile="nope")


# ============================================================
# setup_common_logging：loguru 桥
# ============================================================

class _SinkSpy:
    def __init__(self):
        self.records = []

    def emit(self, event, message, level="info", stage="", payload=None):
        self.records.append({"event": event, "message": message, "level": level,
                             "stage": stage, "payload": payload or {}})


def test_setup_common_logging_bridges_loguru():
    from loguru import logger

    sink = _SinkSpy()
    common.setup_common_logging(sink, level="DEBUG")
    logger.info("桥接测试消息")
    logger.warning("告警消息")
    assert len(sink.records) == 2
    assert sink.records[0]["event"] == "log"
    assert sink.records[0]["level"] == "info"
    assert sink.records[0]["payload"]["raw_level"] == "INFO"
    assert ":" in sink.records[0]["payload"]["module"]  # name:function:line
    logger.remove()


def test_setup_common_logging_redaction_patcher():
    from loguru import logger

    sink = _SinkSpy()
    common.setup_common_logging(sink, level="DEBUG")
    # log_redaction patcher 仍生效（含 password= 的日志被脱敏）
    logger.info("登录 password=abc123 完成")
    assert len(sink.records) == 1
    assert "abc123" not in sink.records[0]["message"]
    logger.remove()


# ============================================================
# terminate_gracefully：终止阶梯
# ============================================================

def _spawn_sleeper():
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows 优雅终止阶梯")
def test_terminate_gracefully_windows_ladder():
    proc = _spawn_sleeper()
    assert proc.poll() is None
    started = time.monotonic()
    common.terminate_gracefully(proc, 2.0)
    elapsed = time.monotonic() - started
    assert proc.poll() is not None
    # 优雅路径应在阶梯时间内完成（远小于 60s sleeper 的生存期）
    assert elapsed < 30


@pytest.mark.skipif(os.name != "nt", reason="已退出进程幂等")
def test_terminate_gracefully_already_exited():
    proc = _spawn_sleeper()
    proc.kill()
    proc.wait(timeout=5)
    common.terminate_gracefully(proc, 1.0)  # 不抛异常即通过


@pytest.mark.skipif(os.name == "nt", reason="POSIX 路径")
def test_terminate_gracefully_posix(monkeypatch):
    monkeypatch.setattr(common.os, "name", "linux")
    proc = _spawn_sleeper()
    common.terminate_gracefully(proc, 1.0)
    assert proc.poll() is not None


# ============================================================
# graceful_exit：协作退出信号
# ============================================================

def test_graceful_exit_event_is_threading_event():
    assert isinstance(common.graceful_exit, threading.Event)
    assert not common.graceful_exit.is_set()
    common.graceful_exit.set()
    assert common.graceful_exit.is_set()
    common.graceful_exit.clear()


# ============================================================
# runtime.EventSink 写失败兜底（T1.5）
# ============================================================

class _BrokenStream:
    def write(self, *_a):
        raise OSError("pipe closed")

    def flush(self):
        raise OSError("pipe closed")


def test_eventsink_fail_counter_sets_graceful_exit():
    from core import runtime

    runtime.graceful_exit.clear()
    sink = runtime.EventSink(task_id="t", stream=_BrokenStream())
    for _ in range(runtime.EventSink.FAIL_LIMIT - 1):
        sink.emit("log", "x")
        assert not runtime.graceful_exit.is_set()
    sink.emit("log", "x")  # 第 FAIL_LIMIT 次
    assert runtime.graceful_exit.is_set()
    runtime.graceful_exit.clear()


def test_eventsink_success_resets_counter():
    from core import runtime
    import io

    runtime.graceful_exit.clear()
    sink_ok = runtime.EventSink(task_id="t", stream=io.StringIO())
    sink_bad = runtime.EventSink(task_id="t", stream=_BrokenStream())
    sink_bad.emit("log", "x")  # bad 失败第 1 次（count=1）
    sink_ok.emit("log", "ok")  # 成功只清零自己的计数，不影响 bad
    sink_bad.emit("log", "x")  # bad 失败第 2 次（count=2，未达上限）
    assert not runtime.graceful_exit.is_set()
    sink_bad.emit("log", "x")  # bad 失败第 3 次（count=3）→ 置位
    assert runtime.graceful_exit.is_set()
    runtime.graceful_exit.clear()


def test_runtime_sleep_raises_on_graceful_exit(monkeypatch):
    from core import runtime

    monkeypatch.setattr(runtime, "_control", None)
    runtime.graceful_exit.set()
    with pytest.raises(runtime.StopRequested):
        runtime.sleep(5)
    with pytest.raises(runtime.StopRequested):
        runtime.checkpoint()
    runtime.graceful_exit.clear()
