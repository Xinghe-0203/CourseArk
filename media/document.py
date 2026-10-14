"""文档媒体类 - 通过'job/document'接口标记PDF文档已阅读"""
from models.media import Media


class Document(Media):
    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str):
        super().__init__(attachment, headers, defaults, course_id)

    def do_finish(self) -> bool:
        return self._do_simple_job_finish(
            api_path='job/document',
            referer='https://mooc1-2.chaoxing.com/ananas/modules/pdf/index.html?v=2020-1103-1706',
            task_name='Document'
        )
