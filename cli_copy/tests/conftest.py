"""核心副本测试也必须使用临时数据，禁止在代码目录生成配置。"""
import pytest


@pytest.fixture(autouse=True)
def isolated_cli_config(tmp_path, monkeypatch):
    """v2.4.0 T2：Config 为纯内存 schema——重置 _data 即可，无文件系统副作用。"""
    from core.config import Config
    monkeypatch.setenv('AUTOCXWEBUI_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(Config, '_data', Config._default_config())
