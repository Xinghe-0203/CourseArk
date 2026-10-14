"""
AutoChaoxingCLI - 线程安全的HTTP请求客户端

核心设计原则：
1. 线程安全 — threading.Lock 保护共享状态（请求时间戳、冷却期）
2. 超星会话与外部API会话隔离，避免Cookie和Host头串用
3. 延迟+随机抖动，避免请求节奏过于规律
4. 反爬虫检测（antispiderShowVerify + 202 + 403）
5. 冷却期120-180秒+随机抖动，防止多线程同时醒来造成请求雪崩
6. User-Agent轮换，降低被识别为自动化的风险
7. 仅对幂等GET请求自动重试（服务器错误5xx）
"""

import random
import threading
import time

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core import runtime
from core.exceptions import AntispiderException, RequestException

# User-Agent 池 — 现代浏览器，轮换使用降低被识别风险
USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.86 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.117 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.6613.120 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.86 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.86 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.6723.117 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.86 Safari/537.36",
]

DEFAULT_USER_AGENT = USER_AGENT_POOL[0]

# 反爬虫检测关键词
ANTISPIDER_KEYWORDS = ['antispiderShowVerify', 'antispider']

# 反爬虫冷却配置
ANTISPIDER_COOLDOWN_BASE = 120  # 基础冷却秒数
ANTISPIDER_COOLDOWN_JITTER = 60  # 冷却抖动范围

# 请求延迟配置
REQUEST_DELAY_BASE = 1.0  # 基础请求延迟
REQUEST_DELAY_JITTER = 0.5  # 延迟抖动范围


class RequestClient:
    """
    HTTP请求客户端（线程安全版）

    改进点：
    - threading.Lock 保护共享状态，确保多线程下请求间隔和冷却期正确
    - 202/403 状态码识别为反爬虫信号
    - User-Agent 轮换
    - 冷却时间120-180秒
    - 请求间隔1.0-1.5秒
    - 服务器5xx错误自动重试
    """

    def __init__(self):
        self._session = requests.Session()
        self._external_session = requests.Session()

        # 配置参数
        self._glo_headers: dict = {}
        self._glo_timeout: int = 10
        self._if_delay: bool = True
        self._time_delay: float = REQUEST_DELAY_BASE
        self._delay_jitter: float = REQUEST_DELAY_JITTER
        self._rotate_ua: bool = True

        # 共享状态（线程锁保护）
        self._last_request_time: float = 0.0
        self._antispider_until: float = 0.0
        self._lock = threading.Lock()
        # requests.Session 不保证线程安全，实际网络操作串行化
        self._session_lock = threading.Lock()

        # UA索引
        self._ua_index = random.randint(0, len(USER_AGENT_POOL) - 1)

    def init_from_config(self, config: dict):
        """
        从配置字典初始化会话

        Args:
            config: 全局配置字典
        """
        advanced = config.get("advanced", {})
        self._glo_timeout = 10
        self._if_delay = True
        self._time_delay = max(0.0, float(advanced.get("request_delay", REQUEST_DELAY_BASE)))
        self._delay_jitter = max(0.0, float(advanced.get("request_delay_jitter", REQUEST_DELAY_JITTER)))
        self._rotate_ua = advanced.get("rotate_ua", True)

        max_retries = max(0, int(advanced.get("max_retries", 3)))
        retry_delay = max(0.0, float(advanced.get("retry_delay", 0.5)))
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=retry_delay,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        # 设置默认headers
        ua = random.choice(USER_AGENT_POOL) if self._rotate_ua else DEFAULT_USER_AGENT
        self._glo_headers = {
            "User-Agent": ua,
        }
        self._session.headers.clear()
        self._session.headers.update(self._glo_headers)
        self._external_session.headers.clear()
        self._external_session.headers.update({"User-Agent": ua})
        logger.success("RequestClient 初始化完成")

    @property
    def session(self) -> requests.Session:
        """获取底层 requests.Session"""
        return self._session

    @property
    def external_session(self) -> requests.Session:
        """获取不含超星Cookie的外部API Session"""
        return self._external_session

    @property
    def lock(self) -> threading.Lock:
        """获取线程锁（供外部模块如视频刷取使用）"""
        return self._lock

    @property
    def antispider_until(self) -> float:
        """获取当前反爬虫冷却截止时间"""
        return self._antispider_until

    @property
    def timeout(self) -> int:
        """获取请求超时时间"""
        return self._glo_timeout

    def _get_random_ua(self) -> str:
        """获取随机User-Agent"""
        return random.choice(USER_AGENT_POOL)

    def _throttle(self):
        """
        请求节流：确保请求间隔，带随机抖动（线程安全）

        如果在反爬虫冷却期内，等待冷却结束（带随机抖动防雪崩）
        """
        while True:
            # 暂停/停止只在请求之间的安全边界生效，不打断进行中的网络请求
            runtime.checkpoint()
            with self._lock:
                now = time.monotonic()
                if now < self._antispider_until:
                    remaining = self._antispider_until - now
                    extra = random.uniform(1, 10)
                    wait = remaining + extra
                    logger.warning(f"反爬虫冷却中，等待 {remaining:.0f}+{extra:.0f} 秒")
                else:
                    min_gap = self._time_delay if self._if_delay else 0
                    gap = min_gap + random.uniform(0, self._delay_jitter)
                    wait = max(0.0, self._last_request_time + gap - now)
                    if wait <= 0:
                        # 预留本次请求时间槽，其他线程醒来后会重新计算
                        self._last_request_time = now
                        return
            runtime.sleep(wait)

    def _trigger_antispider(self, seconds: float = ANTISPIDER_COOLDOWN_BASE):
        """触发反爬虫冷却，带随机抖动（线程安全）"""
        with self._lock:
            jitter = random.uniform(0, ANTISPIDER_COOLDOWN_JITTER)
            new_until = time.monotonic() + seconds + jitter
            # 只延长冷却期，不缩短
            if new_until > self._antispider_until:
                self._antispider_until = new_until
                end_time = time.strftime('%H:%M:%S', time.localtime(time.time() + seconds + jitter))
                logger.warning(f"触发反爬虫，冷却 {seconds + jitter:.0f} 秒 (至 {end_time})")

    @staticmethod
    def _check_antispider(text: str, url: str = ""):
        """检测响应是否为反爬虫页面"""
        if not text:
            return
        text_lower = text.lower()
        for keyword in ANTISPIDER_KEYWORDS:
            if keyword in text_lower:
                raise AntispiderException(url=url, detail=f"检测到反爬虫页面: {keyword}")

    def _inject_ua(self, headers: dict) -> dict:
        """注入随机User-Agent"""
        headers = dict(headers) if headers else {}
        if not self._rotate_ua:
            return headers
        if "User-Agent" not in headers:
            headers["User-Agent"] = self._get_random_ua()
        return headers

    def _handle_response(self, response, url: str, if_full_back: bool):
        """统一处理响应状态码"""
        if if_full_back:
            return response

        if response.status_code == 202:
            self._trigger_antispider(ANTISPIDER_COOLDOWN_BASE)
            raise AntispiderException(url=url, detail="状态码202，触发反爬虫验证")

        if response.status_code == 403:
            self._trigger_antispider(ANTISPIDER_COOLDOWN_BASE)
            text = response.text[:500] if response.text else ""
            if 'passport.chaoxing.com' in text or 'login' in text.lower():
                logger.error("Cookie可能已过期，403响应含登录页面特征")
            raise AntispiderException(url=url, detail="状态码403，被拒绝访问")

        if response.status_code == 200:
            text = response.text
            self._check_antispider(text, url)
            return text
        else:
            raise RequestException(response, 0)

    def get(self, url: str, headers: dict = None, if_full_back: bool = False) -> str:
        """
        GET请求（线程安全版）

        Args:
            url: 请求URL
            headers: 自定义请求头（None则使用全局headers）
            if_full_back: 是否返回完整Response对象

        Returns:
            str或Response: 响应文本或完整Response对象
        """
        self._throttle()
        runtime.checkpoint()
        try:
            if headers is None:
                headers = dict(self._glo_headers)
            headers = self._inject_ua(headers)
            logger.debug(f"GET {url}")
            with self._session_lock:
                response = self._session.get(url=url, headers=headers, timeout=self._glo_timeout)
            return self._handle_response(response, url, if_full_back)
        except (AntispiderException, RequestException):
            raise
        except Exception as e:
            logger.error(f"GET {url} 失败: {e}")
            raise

    def post(self, url: str, headers: dict = None, data=None, if_full_back: bool = False) -> str:
        """
        POST请求（线程安全版）

        Args:
            url: 请求URL
            headers: 自定义请求头
            data: POST数据
            if_full_back: 是否返回完整Response对象

        Returns:
            str或Response: 响应文本或完整Response对象
        """
        self._throttle()
        runtime.checkpoint()
        try:
            if headers is None:
                headers = dict(self._glo_headers)
            headers = self._inject_ua(headers)
            logger.debug(f"POST {url}")
            logger.debug(f"  data: {str(data)[:200]}")
            with self._session_lock:
                response = self._session.post(url=url, headers=headers, data=data, timeout=self._glo_timeout)
            return self._handle_response(response, url, if_full_back)
        except (AntispiderException, RequestException):
            raise
        except Exception as e:
            logger.error(f"POST {url} 失败: {e}")
            raise

    def resolve_url(self, url: str, headers: dict = None, if_loop: bool = False) -> str:
        """
        URL重定向解析（遵守节流机制）

        Args:
            url: 原始URL
            headers: 请求头
            if_loop: 是否只返回一次重定向URL

        Returns:
            str: 最终URL
        """
        logger.debug(f"重定向解析: {url}")
        safe_headers = dict(headers) if headers else {}
        if "User-Agent" not in safe_headers:
            safe_headers["User-Agent"] = self._get_random_ua()

        try:
            current_url = url
            while True:
                self._throttle()
                runtime.checkpoint()
                with self._session_lock:
                    rsp = self._session.get(
                        url=current_url,
                        headers=safe_headers,
                        allow_redirects=False,
                        timeout=self._glo_timeout,
                    )
                location = rsp.headers.get("Location")
                if if_loop:
                    return location or current_url
                if location is None:
                    logger.debug(f"最终URL: {current_url}")
                    return current_url
                current_url = location
        except Exception as e:
            logger.error(f"URL重定向解析失败: {e}")
            return ""


# ============================================================
# 全局单例 + 便捷函数
# ============================================================

_client = RequestClient()


def get_session() -> requests.Session:
    """获取全局Session"""
    return _client.session


def get_external_session() -> requests.Session:
    """获取与超星登录会话完全隔离的Session"""
    return _client.external_session


def init_client(config: dict):
    """从配置初始化全局请求客户端"""
    _client.init_from_config(config)


def get(url: str, headers: dict = None, if_full_back: bool = False) -> str:
    """全局GET请求"""
    return _client.get(url, headers, if_full_back)


def post(url: str, headers: dict = None, data=None, if_full_back: bool = False) -> str:
    """全局POST请求"""
    return _client.post(url, headers, data, if_full_back)


def resolve_url(url: str, headers: dict = None, if_loop: bool = False) -> str:
    """全局URL重定向解析"""
    return _client.resolve_url(url, headers, if_loop)


def get_client() -> RequestClient:
    """获取全局请求客户端实例"""
    return _client


# ============================================================
# 工具函数
# ============================================================

import binascii
import os
import subprocess

import pyDes


def encrypt_des(msg: str, key: str) -> bytes:
    """
    DES加密（用于超星登录密码加密）

    Args:
        msg: 明文
        key: 密钥

    Returns:
        bytes: 加密后的十六进制字节串
    """
    des_obj = pyDes.des(key, key, pad=None, padmode=pyDes.PAD_PKCS5)
    secret_bytes = des_obj.encrypt(msg, padmode=pyDes.PAD_PKCS5)
    return binascii.b2a_hex(secret_bytes)


def clear_console():
    """清空控制台"""
    if os.name == "nt":
        subprocess.run("cls", shell=True, check=False)
    else:
        subprocess.run("clear", shell=True, check=False)


def xpath_first(element, path):
    """
    XPath便捷函数：获取第一个匹配结果

    Args:
        element: lxml元素
        path: XPath表达式

    Returns:
        匹配结果，无匹配返回空字符串
    """
    from lxml.etree import _ElementUnicodeResult

    if element is None:
        return ""
    if isinstance(element, (str, int, bool)):
        return element
    res = element.xpath(path)
    if isinstance(res, bool):
        return res
    if isinstance(res, _ElementUnicodeResult):
        return res
    if isinstance(res, list):
        return res[0] if res else ""
    return ""


def parse_index_list(input_str: str) -> list[int]:
    """
    解析用户输入的序号列表

    支持格式: "1,2,3" 或 "1，2，3"

    Args:
        input_str: 用户输入字符串

    Returns:
        list[int]: 0-based索引列表
    """
    import re

    if not input_str or input_str.strip() == '':
        return []
    indices = []
    for item in re.split("[,，]", input_str.strip()):
        item = item.strip()
        if item:
            try:
                indices.append(int(item) - 1)  # 转为0-based
            except ValueError:
                raise ValueError(f"无效的索引: {item}")
    return indices
