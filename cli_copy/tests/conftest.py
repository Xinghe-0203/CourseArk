"""核心副本测试也必须使用临时数据，禁止在代码目录生成配置。"""
import pytest


@pytest.fixture(autouse=True)
def isolated_cli_config(tmp_path, monkeypatch):
    from core.config import Config
    monkeypatch.setenv('AUTOCXWEBUI_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(Config, '_data', Config._default_config())
    monkeypatch.setattr(Config, '_config_path', str(tmp_path / 'config.yml'))
