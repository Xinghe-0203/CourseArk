"""按域拆分的 API 路由包（v2.4.x 重构）。

约定：路由模块不持有任何状态。db / hub / manager / sessions 是 app.main 上的
惰性单例，测试（tests/conftest.py 的 sandbox / app_client）会整体替换它们——
因此这里一律通过 `from .. import main` 在**调用时**动态取属性，
禁止在模块顶层 `from ..main import db` 之类的一次性绑定。
"""
