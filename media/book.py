"""图书媒体类 - 通过'job'接口标记图书已阅读"""
from models.media import Media


class Book(Media):
    def __init__(self, attachment: dict, headers: dict, defaults: dict, course_id: str):
        super().__init__(attachment, headers, defaults, course_id)

    def do_finish(self) -> bool:
        return self._do_simple_job_finish(
            api_path='job',
            referer='https://mooc1-2.chaoxing.com/ananas/modules/innerbook/index.html?v=2018-0126-1905',
            task_name='Book'
        )
