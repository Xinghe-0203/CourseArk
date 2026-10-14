"""
AutoChaoxingCLI - 用户模型

管理用户登录、Cookie、课程列表等。
"""

import json

from loguru import logger
from lxml import etree

from core.config import Config
from core.exceptions import LoginException, RequestException
from core.request_client import post as doPost, encrypt_des, DEFAULT_USER_AGENT
from models.course import Course


class User:
    """
    用户类

    封装用户登录、Cookie管理和课程列表获取。

    Attributes:
        uid (str): 用户ID
        name (str): 用户名
        username (str): 手机号
        cookie_str (str): Cookie字符串
        headers (dict): 请求头
        course_list (list[Course]): 课程列表
    """

    def __init__(self, username: str = "", password: str = ""):
        self.uid = ""
        self.name = ""
        self.username = username
        self.cookie_str = ""
        self.course_list = []

        # 登录headers（UA由RequestClient统一管理，这里只在登录页面使用默认UA）
        self.login_headers = {
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Host': 'passport2.chaoxing.com',
            'Origin': 'https://passport2.chaoxing.com',
            'Referer': 'https://passport2.chaoxing.com/login?loginType=4&fid=314&newversion=true&refer=http://i.mooc.chaoxing.com',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': DEFAULT_USER_AGENT,
            'X-Requested-With': 'XMLHttpRequest'
        }

        # DES登录
        self._login_with_password(username, password)

    def _login_with_password(self, username: str, password: str):
        """账号密码登录（DES加密）"""
        des_password = encrypt_des(password, "u2oh6Vu^").decode('utf-8')
        rsp = doPost(
            "https://passport2.chaoxing.com/fanyalogin",
            headers=self.login_headers,
            data=f"fid=314&uname={username}&password={des_password}&refer=http%253A%252F%252Fi.mooc.chaoxing.com&t=true",
            if_full_back=True
        )
        if rsp.status_code == 200:
            rsp_json = json.loads(rsp.text)
            if rsp_json.get("status"):
                self._on_login_success(rsp)
                return
            else:
                raise LoginException(rsp_json.get("msg2", "登录失败"))
        else:
            raise RequestException(rsp, 1)

    def _on_login_success(self, rsp):
        """登录成功后的处理"""
        rsp_json = json.loads(rsp.text)
        self.uid = rsp.cookies.get('_uid') or ""
        self.name = rsp_json.get("name") or ""
        if not self.name or self.name == "None":
            self.name = self.uid or self.username

        # 拼接cookie字符串
        cookie_str = ""
        for item in rsp.cookies:
            cookie_str += f"{item.name}={item.value};"
        self.cookie_str = cookie_str

        # 登录后headers（UA由RequestClient._inject_ua统一轮换管理）
        self.headers = {}

        # 同步cookie到Session
        self._sync_cookies_to_session(rsp)

    def _sync_cookies_to_session(self, rsp):
        """将登录响应的cookies同步到全局Session"""
        try:
            from core.request_client import get_session
            session = get_session()
            for item in rsp.cookies:
                # 保留Cookie的域和路径，禁止创建会发往所有域名的supercookie
                domain = item.domain or "passport2.chaoxing.com"
                session.cookies.set(
                    item.name,
                    item.value,
                    domain=domain,
                    path=item.path or "/",
                    secure=item.secure,
                )
        except Exception as e:
            logger.debug(f"同步cookies到Session失败: {e}")

    def get_courses(self):
        """获取课程列表"""
        self.course_list.clear()
        from core.request_client import get as doGet, xpath_first

        html = doGet(
            url="https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courses/list?v=1675234609566&rss=1&start=0&size=500&catalogId=0&superstarClass=0&searchname=",
            headers=self.headers
        )
        ele = etree.HTML(html)
        if ele is None:
            logger.warning("课程列表页面为空或格式异常")
            return
        course_ele = ele.xpath("//ul[@id='courseList']/li")
        for item in course_ele:
            tmp_url = xpath_first(item, "./div[2]/h3/a/@href")
            if tmp_url and tmp_url.startswith("http"):
                course = Course(
                    course_id=xpath_first(item, "./div[1]/input[@class='courseId']/@value"),
                    class_id=xpath_first(item, "./div[1]/input[@class='clazzId']/@value"),
                    url=tmp_url,
                    course_name=xpath_first(item, "./div[2]/h3/a/span/@title"),
                    course_author=xpath_first(item, "./div[2]/p[@class='line2 color3']/@title"),
                    headers=self.headers,
                    if_open=(xpath_first(item, "./div[1]/a[@class='not-open-tip']") == "")
                )
                logger.debug(f"添加课程: {course.course_name}")
                self.course_list.append(course)

    def __str__(self):
        return f"Uid: {self.uid}\nUsername: {self.username}\nName: {self.name}"
