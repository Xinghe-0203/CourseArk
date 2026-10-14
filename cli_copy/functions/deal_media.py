"""
AutoChaoxingCLI - 媒体资源下载处理器
"""

import json
import os
import re
import time

from core import runtime
from core.request_client import get as doGet, get_session
from functions.deal_course import DealCourse


class MediaDownload(DealCourse):
    """媒体下载处理器，继承自DealCourse"""

    def __init__(self, user, course, log):
        super().__init__(user, course, log)
        self.chapter_all = []

    def download_all(self, path: str = "download") -> dict:
        """
        下载课程全部章节中的可下载资源

        Args:
            path: 保存根目录

        Returns:
            dict: {"ok": int, "fail": int, "skipped": int}
        """
        if not self.course.chapter_list:
            self.course.get_chapter()
        if not self.chapter_all:
            for catalog in self.course.chapter_list or []:
                for chapter in catalog.get("child_chapter", []):
                    self.chapter_all.append(chapter)

        stats = {"ok": 0, "fail": 0, "skipped": 0}
        total = len(self.chapter_all)
        self.log.info(f"开始批量下载 '{self.course_name}' 共 {total} 个章节的资源")
        from core.chapter_parser import work_id
        queue = []
        seen = set()
        for chapter in self.chapter_all:
            runtime.checkpoint()
            for card in self.deal_chapter(chapter):
                for media in card.get('attachments', []):
                    if not self._is_downloadable(media):
                        stats['skipped'] += 1
                        continue
                    key = 'download:'+work_id(media)
                    if key not in seen:
                        seen.add(key)
                        queue.append(media)
        runtime.emit('work_plan', '下载范围已读取', stage='download', payload={
            'units': [{'id': 'download:'+work_id(m), 'name': (m.get('property') or {}).get('name'), 'kind': 'download'} for m in queue],
            'sealed': True})
        for media in queue:
            runtime.checkpoint()
            if self.do_download(path, media):
                stats['ok'] += 1
            else:
                stats['fail'] += 1
        self.log.success(
            f"批量下载完成: 成功{stats['ok']}个 | 失败{stats['fail']}个 | 跳过{stats['skipped']}个"
        )
        runtime.emit("task_progress", "资源下载统计", stage="download", payload={
            "course_name": self.course_name,
            "success": stats["ok"],
            "failed": stats["fail"],
            "skipped": stats["skipped"],
        })
        return stats

    @staticmethod
    def _is_downloadable(media: dict) -> bool:
        """判断媒体附件是否含有可下载的资源ID"""
        prop = media.get("property") or {}
        if prop.get("objectid"):
            return True
        media_type = media.get("type")
        return media_type in ("document", "book", "video", "audio") and bool(media.get("objectId"))

    def deal_course(self):
        """获取并展示课程章节列表"""
        self.log.info(f"获取'{self.course_name}'课程的章节中...")
        if not self.course.chapter_list:
            self.course.get_chapter()
        if self.course.chapter_list:
            self.log.success(f"获取'{self.course_name}'课程章节成功")
            time.sleep(0.4)
            self.chapter_all = []
            ind = 1
            for catalog_item in self.course.chapter_list:
                self.log.info(catalog_item.get("catalog_name"))
                for chapter_item in catalog_item.get("child_chapter"):
                    self.log.info(f"{ind}.  {'----' * (chapter_item.get('depth') + 1)} {chapter_item.get('name')}")
                    self.chapter_all.append(chapter_item)
                    ind += 1
                self.log.info("-" * 35)
            self.log.success(f"'{self.course_name}'课程章节展示完毕")
        else:
            self.log.warning(f"'{self.course_name}'课程章节数为零")

    def do_download(self, path: str = "", attachment: dict = None):
        from core.chapter_parser import work_id
        attachment = attachment or {}
        key = 'download:' + work_id(attachment)
        name = (attachment.get('property') or {}).get('name') or '课程资源'
        runtime.emit('work_plan', '资源已读取', stage='download', payload={
            'units': [{'id': key, 'name': name, 'kind': 'download'}]})
        runtime.emit('work_started', '开始下载', stage='download', payload={'id': key, 'name': name, 'status': 'running'})
        ok = False
        try:
            ok = bool(self._download_file(path, attachment))
            return ok
        finally:
            runtime.emit('work_result', '资源已保存' if ok else '资源未保存', stage='download',
                         level='info' if ok else 'warning', payload={'id': key, 'name': name, 'kind': 'download',
                                                                   'status': 'succeeded' if ok else 'failed'})

    def _download_file(self, path: str = "", attachment: dict = None):
        """下载单个媒体资源"""
        if attachment is None:
            attachment = {}
        prop = attachment.get("property")
        # objectid 可能位于 property（文档/图书）或附件顶层（视频）
        objectid = (prop.get("objectid") if prop else None) or attachment.get("objectId")
        name = ((prop or {}).get("name") or (prop or {}).get("bookname")
                or attachment.get("name") or "未知文件")
        if objectid is None:
            self.log.error(f"{name} 文件ID获取失败，跳过")
            return

        _headers = {
            'Accept': '*/*',
            'Host': 'mooc1-2.chaoxing.com',
            'Referer': 'https://mooc1-2.chaoxing.com/ananas/modules/audio/index.html?v=2022-1028-1705',
            'X-Requested-With': 'XMLHttpRequest'
        }
        download_headers = {
            "referer": "https://mooc1-2.chaoxing.com/ananas/modules/video/index.html?v=2021-0924-1446",
        }
        download_headers.update(self.user.headers)
        _headers.update(self.user.headers)

        # 创建保存目录
        child_path = os.path.join(path, self._safe_component(self.course_name, "未命名课程"))
        os.makedirs(child_path, exist_ok=True)

        # 获取文件状态
        _status = doGet(
            url=f"https://mooc1-2.chaoxing.com/ananas/status/{objectid}?_dc={int(time.time() * 1000)}",
            headers=_headers
        )
        if not _status:
            self.log.error(f"{name} 文件状态获取失败，跳过")
            return
        try:
            _status_json = json.loads(_status)
        except json.JSONDecodeError as e:
            self.log.error(f"{name} 文件状态解析失败: {e}")
            return

        filename = _status_json.get('filename')
        # 选择下载源
        if _status_json.get("httphd"):
            _url = _status_json.get('httphd')
        elif _status_json.get("pagenum") is not None:
            _url = _status_json.get('pdf')
        else:
            _url = _status_json.get('http')
        if not _url:
            self.log.error(f"{name} 未找到可用的下载地址，跳过")
            return False

        # 流式下载（使用全局session保持登录Cookie）
        save_path = os.path.join(child_path, self._get_save_name(name, filename))
        temp_path = save_path + ".part"
        try:
            session = get_session()
            with session.get(url=_url, headers=download_headers, stream=True, timeout=(10, 60)) as rsp:
                rsp.raise_for_status()
                length_all = int(rsp.headers.get('content-length', 0))
                self.log.info(f"开始下载文件'{name}'")
                length_already = 0
                with open(temp_path, "wb") as f:
                    for chunk in rsp.iter_content(chunk_size=1024 * 1024):
                        # 分块边界检查停止/暂停，避免大文件下载无法中断
                        runtime.checkpoint()
                        if chunk:
                            length_already += len(chunk)
                            if length_all > 0:
                                percent = int(length_already / length_all * 100)
                                from core.chapter_parser import work_id
                                runtime.emit("work_progress", '正在下载', stage="download", payload={
                                    'id': 'download:'+work_id(attachment), 'name': name, 'current': length_already,
                                    "media": name,
                                    "received": length_already,
                                    "total": length_all,
                                    "percent": percent,
                                })
                            f.write(chunk)
                if length_all > 0 and length_already != length_all:
                    raise IOError(f"文件长度不一致: {length_already}/{length_all}")
            os.replace(temp_path, save_path)
            self.log.success(f"'{name}'下载完成")
            return True
        except Exception as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            self.log.error(f"'{name}'下载失败: {e}")
            return False

    def _get_save_name(self, name: str, filename: str) -> str:
        """生成文件保存名称"""
        source_name = filename or name or "未知文件"
        extension = os.path.splitext(source_name)[1]
        safe_name = self._safe_component(name or os.path.splitext(source_name)[0], "未知文件")
        current_extension = os.path.splitext(safe_name)[1]
        if extension and current_extension.lower() != extension.lower():
            safe_name = os.path.splitext(safe_name)[0] + extension
        return self._safe_component(safe_name, "未知文件")

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        """生成不含路径穿越和Windows非法字符的单个路径组件。"""
        value = os.path.basename(str(value or "").replace("\\", "/"))
        value = re.sub(r'[\x00-\x1f\/:*?"<>|]', '', value).strip().rstrip('. ')
        if not value or value.upper() in {
            "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            return fallback
        return value[:180]
