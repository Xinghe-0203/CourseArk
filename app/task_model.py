"""
任务模型：功能类型、状态机、参数快照校验

设计要点：
- 参数遵循“全局默认值 + 每个任务覆盖”，提交时冻结为快照，后续修改全局设置不影响历史任务
- 所有写接口都走 Pydantic 模型校验枚举、范围与必填项
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from . import settings

FEATURES = ("course_all", "chapter_exam", "independent_homework", "video",
            "learn_count", "download")

FEATURE_LABELS = {
    "course_all": "一键完成课程任务",
    "chapter_exam": "章节测验答题",
    "independent_homework": "独立作业答题",
    "video": "刷取视频时长",
    "learn_count": "刷取学习次数",
    "download": "下载课程资源",
}

# 状态机允许的转换
TRANSITIONS = {
    "pending": {"starting", "stopped", "failed", "interrupted"},
    "starting": {"logging_in", "running", "failed", "stopping", "interrupted"},
    "logging_in": {"loading_courses", "failed", "stopping", "paused", "interrupted"},
    "loading_courses": {"running", "failed", "stopping", "paused", "interrupted"},
    "running": {"pausing", "paused", "stopping", "stopped", "succeeded", "failed", "interrupted"},
    "pausing": {"paused", "stopping", "running", "failed", "interrupted"},
    "paused": {"running", "stopping", "stopped", "failed", "interrupted"},
    "stopping": {"stopped", "failed", "interrupted"},
    "succeeded": set(),
    "failed": set(),
    "stopped": set(),
    "interrupted": set(),
}

ACTIVE_STATES = {"pending", "starting", "logging_in", "loading_courses", "running",
                 "pausing", "paused", "stopping"}
TERMINAL_STATES = {"succeeded", "failed", "stopped", "interrupted"}
CONTROLLABLE_STATES = {"pending", "starting", "logging_in", "loading_courses",
                       "running", "pausing", "paused", "stopping"}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, set())


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES


# ============================================================
# 参数模型
# ============================================================

class VideoParams(BaseModel):
    mode: str = "hybrid"
    max_workers: int = Field(default=8, ge=0, le=200)
    random_progress: bool = True

    @field_validator("mode")
    @classmethod
    def _mode(cls, value):
        if value not in {"instant", "real_time", "hybrid"}:
            raise ValueError("视频模式必须是 instant / real_time / hybrid")
        return value


class AnswerParams(BaseModel):
    mode: str = "ai"
    fallback_to_tiku: bool = True
    no_answer_action: str = "skip"
    submit_delay: float = Field(default=2, ge=0, le=600)
    auto_submit: bool = True

    @field_validator("mode")
    @classmethod
    def _mode(cls, value):
        if value not in {"ai", "tiku", "manual"}:
            raise ValueError("答题模式必须是 ai / tiku / manual")
        return value

    @field_validator("no_answer_action")
    @classmethod
    def _action(cls, value):
        if value not in {"skip", "random"}:
            raise ValueError("无答案策略必须是 skip 或 random")
        return value


class LearnCountParams(BaseModel):
    times: int = Field(default=10, ge=1, le=9999)
    dwell: float = Field(default=30, ge=0, le=3600)


class DownloadParams(BaseModel):
    path: str = "data/downloads"
    scope: str = "all"
    chapters: List[str] = Field(default_factory=list)

    @field_validator("scope")
    @classmethod
    def _scope(cls, value):
        if value not in {"all", "chapters"}:
            raise ValueError("下载范围必须是 all 或 chapters")
        return value

    @model_validator(mode="after")
    def _selected_chapters(self):
        self.chapters = list(dict.fromkeys(str(item).strip() for item in self.chapters if str(item).strip()))
        if self.scope == "chapters" and not self.chapters:
            raise ValueError("指定章节下载时必须填写至少一个章节 ID")
        return self


class CourseAllParams(BaseModel):
    """一键完成课程任务点的参数（不含独立作业：那是独立功能）"""
    video: Optional[VideoParams] = None
    answer: Optional[AnswerParams] = None


class TaskParams(BaseModel):
    """单个子任务的完整参数快照"""
    video: VideoParams = Field(default_factory=VideoParams)
    answer: AnswerParams = Field(default_factory=AnswerParams)
    learn_count: LearnCountParams = Field(default_factory=LearnCountParams)
    download: DownloadParams = Field(default_factory=DownloadParams)
    course_all: CourseAllParams = Field(default_factory=CourseAllParams)
    advanced: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_settings(cls, overrides: dict = None, feature: str = '') -> "TaskParams":
        """以全局默认值为基础，叠加任务级覆盖"""
        base = settings.resolve("defaults", {}) or {}
        merged = {
            "video": dict(base.get("video", {})),
            "answer": dict(base.get("answer", {})),
            "learn_count": dict(base.get("learn_count", {})),
            "download": dict(base.get("download", {})),
            "course_all": dict(base.get("course_all", {})),
            "advanced": dict(settings.resolve("advanced", {}) or {}),
        }
        for key, value in (overrides or {}).items():
            if value is None:
                continue
            if key == "advanced":
                merged["advanced"] = {**merged["advanced"], **value}
            elif isinstance(value, dict):
                merged[key] = {**merged.get(key, {}), **value}
        if feature and feature != 'download':
            merged['download'] = DownloadParams().model_dump()
        return cls.model_validate(merged)

    def snapshot(self) -> dict:
        return self.model_dump()

    def for_feature(self, feature: str) -> dict:
        """只保留该功能真正用到的参数，避免快照里出现无关字段"""
        data = self.model_dump()
        keep = {
            "course_all": ("video", "answer", "course_all", "advanced"),
            "chapter_exam": ("answer", "advanced"),
            "independent_homework": ("answer", "advanced"),
            "video": ("video", "advanced"),
            "learn_count": ("learn_count", "advanced"),
            "download": ("download", "advanced"),
        }[feature]
        return {key: data[key] for key in keep}


# ============================================================
# 提交模型
# ============================================================

class TaskTarget(BaseModel):
    account_id: str
    course_id: str
    class_id: str = ""
    cpi: str = ""
    course_name: str = ""


class RunCreateRequest(BaseModel):
    feature: str
    targets: List[TaskTarget] = Field(min_length=1)
    params: Dict[str, Any] = Field(default_factory=dict)
    note: str = ""

    @field_validator("feature")
    @classmethod
    def _feature(cls, value):
        if value not in FEATURES:
            raise ValueError(f"功能类型必须是 {list(FEATURES)} 之一")
        return value


def new_task_id() -> str:
    return uuid.uuid4().hex


def new_run_id() -> str:
    return "run-" + uuid.uuid4().hex[:12]


def build_tasks(request: RunCreateRequest) -> tuple:
    """把请求展开为批次与子任务记录"""
    from . import accounts

    run_id = new_run_id()
    created = time.time()
    params = TaskParams.from_settings(request.params, feature=request.feature)
    snapshot = params.for_feature(request.feature)

    tasks = []
    for target in request.targets:
        account = accounts.get_account(target.account_id, public=False)
        if not account:
            raise ValueError(f"账号不存在: {target.account_id}")
        if not account.get("enabled", True):
            raise ValueError(f"账号已停用: {account.get('label', target.account_id)}")
        tasks.append({
            "id": new_task_id(),
            "run_id": run_id,
            "account_id": target.account_id,
            "account_label": account.get("label", ""),
            "course_id": target.course_id,
            "class_id": target.class_id,
            "cpi": target.cpi,
            "course_name": target.course_name,
            "feature": request.feature,
            "status": "pending",
            "params": snapshot,
            "created_at": created,
        })
    return run_id, tasks, params
