"""
AutoChaoxingCLI - 视频时长刷取处理器

支持 ThreadPoolExecutor 并发控制（0-200线程）：
- instant 模式：立即完成视频任务点
- real_time 模式：按实际时长刷取视频，定期发送播放进度

反爬虫策略：
- 使用全局 RequestClient 的冷却机制（120-180秒）
- 视频进度报告加入随机偏移（0-30秒），避免多线程同时请求
- 触发反爬虫后自动等待重试
"""

import random
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from loguru import logger

from core.config import Config
from core.exceptions import AntispiderException
from core.request_client import get as doGet, get_client
from media.video import Video, VIDEO_REFERER_VERSION
from media.live import Live

# 反爬虫重试配置
MAX_ANTISPIDER_RETRY = 3

# 视频进度报告间隔（秒）+ 随机偏移
PROGRESS_REPORT_INTERVAL = 60
PROGRESS_REPORT_JITTER = 30
FINAL_CONFIRM_DELAYS = (5, 10, 15)


def _doGet_with_retry(url, headers, video_name, max_retry=MAX_ANTISPIDER_RETRY):
    """带反爬虫重试的doGet封装"""
    for attempt in range(max_retry):
        try:
            return doGet(url, headers)
        except AntispiderException as e:
            if attempt < max_retry - 1:
                # 读取全局冷却剩余时间
                client = get_client()
                with client.lock:
                    remaining = client.antispider_until - time.monotonic()
                wait_time = max(remaining + 5, 30)
                logger.warning(f"视频'{video_name}'触发反爬虫(第{attempt+1}次)，等待{wait_time:.0f}秒后重试...")
                time.sleep(wait_time)
            else:
                logger.error(f"视频'{video_name}'反爬虫重试{max_retry}次仍失败，放弃")
                raise


class DealVideo:
    """
    视频时长刷取处理器

    支持 ThreadPoolExecutor 并发控制，可配置 0-200 线程。
    """

    DEFAULT_THREAD_TIMEOUT = 3600 * 2  # 2小时

    def __init__(self, user, course, log):
        self.user = user
        self.course = course
        self.log = log

    @staticmethod
    def run_video(video: Video, user, log, all_time: int = 0):
        """
        执行视频时长刷取（等时长模式）

        Args:
            video: 视频对象
            user: 用户对象
            log: 日志对象
            all_time: 要刷取的时长（分钟），0表示刷取全部时长
        """
        try:
            video.last_error = ''
            video_status = video.get_status()
            if not video_status:
                video.last_error = '视频状态读取失败，请检查网络或平台验证'
                log.error(f"视频'{video.name}'状态获取失败")
                return False

            duration = video_status.get('duration')
            dtoken = video_status.get('dtoken')

            if duration is None or dtoken is None:
                video.last_error = '平台视频状态缺少时长或播放令牌'
                log.error(f"视频'{video.name}'缺少duration或dtoken")
                return False
            try:
                duration = int(float(duration))
            except (TypeError, ValueError):
                video.last_error = '平台返回的视频时长格式无效'
                log.error(f"视频'{video.name}'时长格式无效({duration})")
                return False
            if duration <= 0:
                video.last_error = '平台返回的视频时长无效'
                log.error(f"视频'{video.name}'时长无效({duration})")
                return False

            _headers = {
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Content-Type': 'application/json',
                'Sec-Fetch-Dest': 'empty',
                'Host': 'mooc1.chaoxing.com',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'Referer': f'https://mooc1.chaoxing.com/ananas/modules/video/index.html?v={VIDEO_REFERER_VERSION}'
            }
            _headers.update(user.headers)

            # 断点续传：若服务端/附件已记录播放进度，则从该进度继续，避免从头重刷
            attachment = getattr(video, "attachment", None) or {}
            try:
                initial_play = int(float(attachment.get("playTime") or 0)) // 1000
            except (TypeError, ValueError):
                initial_play = 0
            initial_play = max(0, min(initial_play, duration))
            # 终点缓存不能代表通过；未确认的任务必须实际播放。
            if initial_play >= duration and not Video.is_passed_response(attachment):
                initial_play = 0
            if initial_play > 0:
                log.info(f"视频'{video.name}'检测到已观看{initial_play}秒，将断点续刷")

            # 计算目标刷取秒数
            if all_time > 0:
                target_seconds = min(all_time * 60, duration)
            else:
                target_seconds = duration
            target_seconds = max(target_seconds, initial_play)

            time_all_min = round(duration / 60, 2)

            def _refresh_status():
                """上报被拦截时刷新视频令牌，返回是否刷新成功"""
                nonlocal duration, dtoken
                status = video.get_status()
                if not status or not status.get('dtoken') or status.get('duration') is None:
                    return False
                dtoken = status.get('dtoken')
                try:
                    duration = int(float(status.get('duration')))
                except (TypeError, ValueError):
                    pass
                return True

            def _report(playing_time, play_type):
                """上报播放进度，遇验证码/403时刷新令牌并重试一次"""
                _url = video.get_url(playing_time, duration, dtoken, play_type)
                try:
                    return _doGet_with_retry(_url, _headers, video.name)
                except AntispiderException:
                    if _refresh_status():
                        logger.warning(f"视频'{video.name}'上报被拦截，已刷新令牌后重试")
                        _url = video.get_url(min(playing_time, duration), duration, dtoken, play_type)
                        return _doGet_with_retry(_url, _headers, video.name)
                    raise

            # 发送播放开始请求
            _rsp = _report(initial_play, 3)
            logger.debug(_rsp)

            # 随机偏移避免多视频同时上报
            progress_jitter = (
                random.uniform(0, PROGRESS_REPORT_JITTER)
                if Config.get("video.random_progress", True) else 0
            )
            start_time = time.monotonic()

            # 只上报尚未到终点的整分钟进度，终点统一在循环后发送
            for playing_time in range(initial_play + PROGRESS_REPORT_INTERVAL,
                                      target_seconds, PROGRESS_REPORT_INTERVAL):
                target_elapsed = (playing_time - initial_play) + progress_jitter
                elapsed = time.monotonic() - start_time
                wait_time = target_elapsed - elapsed
                if wait_time > 0:
                    time.sleep(wait_time)

                log.info(f"'{video.name}' 当前刷取时长{playing_time // 60}分钟, 总时长{time_all_min}分钟")
                _rsp = _report(playing_time, 0)
                logger.debug(_rsp)

            target_elapsed = (target_seconds - initial_play) + progress_jitter
            elapsed = time.monotonic() - start_time
            wait_time = target_elapsed - elapsed
            if wait_time > 0:
                time.sleep(wait_time)

            is_complete = target_seconds >= duration
            play_type = 4 if is_complete else 0
            log.info(f"'{video.name}' 当前刷取时长{round(target_seconds / 60, 2)}分钟, 总时长{time_all_min}分钟")
            _rsp = _report(target_seconds, play_type)
            logger.debug(_rsp)

            if not is_complete:
                return bool(_rsp)
            for delay in FINAL_CONFIRM_DELAYS:
                if Video.is_passed_response(_rsp):
                    return True
                time.sleep(delay)
                _rsp = _report(target_seconds, play_type)
                logger.debug(_rsp)
            if Video.is_passed_response(_rsp):
                return True
            try:
                response = _rsp if isinstance(_rsp, dict) else json.loads(_rsp)
            except (TypeError, ValueError):
                response = {}
            if isinstance(response, dict) and any(response.get(k) in (True, 'true') for k in ('videoTimeLimit', 'hasJobLimit')):
                video.last_error = '平台限制当前视频学习，请检查课程开放时间和任务限制'
            else:
                video.last_error = '已按实际时长播放，但平台尚未确认视频任务点，请在学习通核对后重试'
            return False

        except AntispiderException:
            video.last_error = '视频播放被平台验证拦截，请完成验证后重试'
            log.error(f"视频'{video.name}'因反爬虫验证失败，刷取中断")
            return False
        except Exception as e:
            video.last_error = f'视频播放异常：{e}'
            log.error(f"视频'{video.name}'刷取异常: {e}")
            return False

    @staticmethod
    def run_live(live: Live, user, log):
        """执行直播时长刷取"""
        try:
            live_status = live.get_status()
            if not live_status:
                log.error(f"直播'{live.name}'状态获取失败")
                return False

            temp = live_status.get("temp")
            data = temp.get("data") if temp else None
            duration = data.get('duration') if data else None

            if duration is None or duration <= 0:
                log.error(f"直播'{live.name}'时长获取失败或无效")
                return False

            _dis = (duration + 59) // 60
            for i in range(int(_dis)):
                log.info(f"'{live.name}' 当前刷取时长{i + 1}分钟, 总时长{_dis}分钟")
                if not live.do_finish():
                    log.error(f"直播'{live.name}'第{i + 1}分钟上报失败")
                    return False
                if i < int(_dis) - 1:
                    time.sleep(59)

            return True
        except AntispiderException:
            log.error(f"直播'{live.name}'因反爬虫验证失败，刷取中断")
            return False
        except Exception as e:
            log.error(f"直播'{live.name}'刷取异常: {e}")
            return False

    def batch_run_videos(self, video_tasks: list[dict], max_workers: int = 5) -> dict:
        """
        批量并发刷取视频（ThreadPoolExecutor）

        Args:
            video_tasks: 视频任务列表，每个元素: {"video": Video, "mode": "instant"|"real_time"}
            max_workers: 最大并发线程数 (0=不限制, 1-200=指定)

        Returns:
            dict: {"success": int, "failed": int, "total": int}
        """
        total = len(video_tasks)
        if total == 0:
            return {"success": 0, "failed": 0, "total": 0}

        # 处理 max_workers=0 的情况（不限制）
        if max_workers <= 0:
            max_workers = min(total, 200)
        max_workers = max(1, min(max_workers, 200))  # 确保在 1-200 范围内

        self.log.info(f"开始并发刷取 {total} 个视频，最大并发数: {max_workers}")

        success = 0
        failed = 0

        def _process_video(task):
            video = task["video"]
            mode = task.get("mode", "instant")
            try:
                if mode == "real_time":
                    return DealVideo.run_video(video, self.user, self.log)
                elif mode == "live":
                    return DealVideo.run_live(video, self.user, self.log)
                else:
                    # 秒刷是一次静默探测，未通过或异常都转为真实播放。
                    try:
                        with logger.contextualize(instant_probe=True):
                            result = video.do_finish()
                    except Exception:
                        result = False
                    if result:
                        return True
                    return DealVideo.run_video(video, self.user, self.log)
            except Exception as e:
                logger.error(f"视频'{video.name}'处理异常: {e}")
                return False

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process_video, task): task for task in video_tasks}
            for future in as_completed(futures):
                task = futures[future]
                video_name = task["video"].name or "未命名"
                try:
                    # as_completed 产出的 future 已经结束，此处不再伪装无效的超时控制
                    result = future.result()
                    if result:
                        success += 1
                        self.log.success(f"  [OK] {video_name}")
                    else:
                        failed += 1
                        reason = getattr(task['video'], 'last_error', '')
                        if not isinstance(reason, str) or not reason:
                            reason = '平台尚未确认任务点'
                        self.log.error(f"视频'{video_name}'未完成：{reason}")
                except Exception as e:
                    failed += 1
                    self.log.error(f"  [FAIL] {video_name}: {e}")

        return {"success": success, "failed": failed, "total": total}

    def get_videos(self) -> List[Video]:
        """获取课程中的所有视频对象"""
        from functions.deal_course import DealCourse
        _data = self.course.get_progress_data()
        _video_list = []
        seen_object_ids = set()
        for i in _data:
            for j in i.get('list', []):
                if j.get('type') == '视频':
                    _dc = DealCourse(self.user, self.course, self.log)
                    attachments = _dc.deal_chapter({'knowledge_id': j.get("chapterId")})
                    for attach_item in attachments:
                        medias = attach_item.get("attachments") or []
                        defaults = attach_item.get("defaults") or {}
                        for media in medias:
                            media_type = media.get("type")
                            media_property = media.get('property')
                            media_module = media_property.get('module') if media_property else None
                            media_name = media_property.get('name') if media_property else None
                            object_id = media.get("objectId")
                            if (media_type == "video" and media_module != "insertaudio"
                                    and object_id and object_id not in seen_object_ids):
                                seen_object_ids.add(object_id)
                                _video_list.append(Video(media, self.user.headers, defaults, self.course.course_id, name=media_name))
        return _video_list
