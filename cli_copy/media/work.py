"""
AutoChaoxingCLI - 作业媒体类

处理作业任务点的完成逻辑。
作业任务通过 'job/work' 接口完成。
实际答题和提交由 DealExam 处理。
"""

from loguru import logger
from models.media import Media


class Work(Media):
    """作业媒体类"""

    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str):
        super().__init__(attachment, headers, defaults, course_id)

    def do_finish(self) -> bool:
        """完成作业任务点"""
        jtoken = self.attachment.get("jtoken")
        if not jtoken:
            logger.debug("作业任务点缺少jtoken，跳过标记（答题提交后将自动完成）")
            return True
        return self._do_simple_job_finish(
            api_path='job/work',
            referer='https://mooc1-2.chaoxing.com/ananas/modules/work/index.html',
            task_name='Work'
        )
