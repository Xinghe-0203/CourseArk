import type { Task } from "./types";
export const statuses: Record<string, string> = {
  pending: "排队中",
  starting: "准备中",
  logging_in: "登录中",
  loading_courses: "读取课程",
  running: "进行中",
  pausing: "正在暂停",
  paused: "已暂停",
  stopping: "正在停止",
  succeeded: "已完成",
  failed: "需处理",
  stopped: "已停止",
  interrupted: "已中断",
};
export const features: Record<string, string> = {
  course_all: "课程任务点",
  independent_homework: "独立作业",
};
export const categories: Record<string, string> = {
  video: "视频学习",
  audio: "音频学习",
  live: "直播学习",
  exam: "章节测验",
  homework: "独立作业",
  download: "资源下载",
  course: "课程读取",
  finish: "任务结果",
  login: "账号登录",
  sync: "课程同步",
  llm: "AI 服务",
  answer: "答题与提交",
  font: "题目识别",
  media: "视频与资源",
  chapter: "章节解析",
  network: "网络连接",
  antispider: "平台验证",
  bank: "题库",
  worker: "运行服务",
  task: "任务结果",
  general: "其他问题",
  progress: "学习进度",
};
export const active = (t: Task) =>
  [
    "starting",
    "logging_in",
    "loading_courses",
    "running",
    "pausing",
    "stopping",
  ].includes(t.status);
export const terminal = (t: Task) =>
  ["succeeded", "failed", "stopped", "interrupted"].includes(t.status);
export function groupTasks(tasks: Task[]) {
  const groups = new Map<
    string,
    { id: string; label: string; tasks: Task[] }
  >();
  for (const task of tasks) {
    if (!groups.has(task.account_id))
      groups.set(task.account_id, {
        id: task.account_id,
        label: task.account_label || "未命名账号",
        tasks: [],
      });
    groups.get(task.account_id)!.tasks.push(task);
  }
  return [...groups.values()];
}
export function percent(task: Task): number | null {
  return task.progress?.percent ?? null;
}
export function date(ts?: number) {
  return ts
    ? new Date(ts * 1000).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}
export function chapters(text: string) {
  return [
    ...new Set(
      text
        .split(/[\s,，、;；]+/)
        .map((x) => x.trim())
        .filter(Boolean),
    ),
  ];
}
