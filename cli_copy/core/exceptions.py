"""
AutoChaoxingCLI - 自定义异常类

定义项目中使用的所有自定义异常。
"""


class LoginException(Exception):
    """登录异常 - 登录失败时抛出"""

    def __init__(self, msg: str):
        self.msg = msg

    def __str__(self):
        return self.msg


class RequestException(Exception):
    """网络请求异常 - HTTP请求失败时抛出"""

    def __init__(self, response, method: int = 0):
        self.response = response
        self.method = method  # 0=GET, 1=POST
        if isinstance(response, str):
            self.text = response
        else:
            self.text = response.text if hasattr(response, 'text') else str(response)

    def __str__(self):
        if isinstance(self.response, str):
            return self.response
        url = getattr(self.response, 'url', 'unknown')
        status = getattr(self.response, 'status_code', 'unknown')
        method_name = ['GET', 'POST'][self.method] if self.method in (0, 1) else 'UNKNOWN'
        return f"Url: {url}\nMethod: {method_name}\nStatus: {status}"


class AntispiderException(Exception):
    """反爬虫检测异常 - 服务器返回反爬虫验证页面时抛出"""

    def __init__(self, url: str = "", detail: str = "触发反爬虫验证"):
        self.url = url
        self.detail = detail

    def __str__(self):
        return f"反爬虫检测: {self.detail} (URL: {self.url})"


class CookieExpiredException(Exception):
    """Cookie过期异常 - 登录Cookie失效时抛出"""

    def __init__(self, detail: str = "Cookie已过期"):
        self.detail = detail

    def __str__(self):
        return f"Cookie过期: {self.detail}"


class VideoException(Exception):
    """视频处理异常 - 视频刷取过程中出错时抛出"""

    def __init__(self, video_name: str = "", detail: str = ""):
        self.video_name = video_name
        self.detail = detail

    def __str__(self):
        return f"视频异常: {self.detail} (视频: {self.video_name})"
