"""
AutoChaoxingCLI - 通知推送模块

支持：ServerChan / Bark / Telegram
"""

from loguru import logger
from urllib.parse import quote

from core.request_client import get_external_session


class Notification:
    """通知推送类"""

    def __init__(self, config: dict = None):
        config = config or {}
        self.enabled = config.get("enabled", False)
        self.providers = []

        sc = config.get("server_chan", {})
        if sc.get("enabled") and sc.get("sendkey"):
            self.providers.append(("serverchan", sc))

        bark = config.get("bark", {})
        if bark.get("enabled") and bark.get("key"):
            self.providers.append(("bark", bark))

        tg = config.get("telegram", {})
        if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
            self.providers.append(("telegram", tg))

    def send(self, title: str, content: str) -> bool:
        """发送通知"""
        if not self.enabled or not self.providers:
            return False

        any_success = False
        for provider_name, provider_config in self.providers:
            try:
                if provider_name == "serverchan":
                    ok = self._send_serverchan(provider_config, title, content)
                elif provider_name == "bark":
                    ok = self._send_bark(provider_config, title, content)
                elif provider_name == "telegram":
                    ok = self._send_telegram(provider_config, title, content)
                else:
                    ok = False
                any_success = any_success or ok
            except Exception as e:
                logger.error(f"通知发送失败({provider_name}): {e}")
        return any_success

    def _send_serverchan(self, config: dict, title: str, content: str):
        url = f"https://sctapi.ftqq.com/{config['sendkey']}.send"
        resp = get_external_session().post(url, data={"title": title, "desp": content}, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') == 0:
            logger.success("ServerChan通知发送成功")
            return True
        return False

    def _send_bark(self, config: dict, title: str, content: str):
        server = config.get("server", "https://api.day.app")
        url = f"{server.rstrip('/')}/{quote(config['key'], safe='')}/{quote(title, safe='')}/{quote(content, safe='')}"
        resp = get_external_session().get(url, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') == 200:
            logger.success("Bark通知发送成功")
            return True
        return False

    def _send_telegram(self, config: dict, title: str, content: str):
        message = f"*{title}*\n\n{content}"
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        resp = get_external_session().post(url, json={
            "chat_id": config['chat_id'],
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get('ok'):
            logger.success("Telegram通知发送成功")
            return True
        return False
