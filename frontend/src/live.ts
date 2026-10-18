import type { LiveUnit, Task } from "./types";
import { active } from "./format";

/** 秒数格式化为 hh:mm:ss；无效值用占位符，避免小窗出现 NaN。 */
export function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds))
    return "--:--:--";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(hours)}:${pad(minutes)}:${pad(secs)}`;
}

/** 预计剩余：缺失时显示「计算中」，不显示占位符。 */
export function formatEta(seconds?: number | null): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds))
    return "计算中";
  return formatDuration(seconds);
}

/** 已用时：优先后端 live，其次用 started_at / finished_at 本地兜底。 */
export function elapsedSeconds(task: Task, now = Date.now() / 1000) {
  const live = task.live;
  if (live?.elapsed_seconds !== null && live?.elapsed_seconds !== undefined)
    return Math.max(0, live.elapsed_seconds);
  if (!task.started_at) return null;
  const end = task.finished_at || now;
  return Math.max(0, end - task.started_at);
}

/** 最近动作：live.activity → 当前项名称 → 阶段兜底。 */
export function activityOf(task: Task): string {
  const activity = (task.live?.activity || "").trim();
  if (activity) return activity;
  const current = task.progress?.active?.[0]?.name?.trim();
  if (current) return `正在处理「${current}」`;
  if (task.status === "loading_courses") return "正在读取课程";
  if (task.status === "logging_in") return "正在登录学习通";
  if (task.status === "pausing") return "正在暂停任务";
  if (task.status === "stopping") return "正在停止任务";
  return "正在准备任务";
}

export function unitPercent(unit?: LiveUnit | null): number | null {
  if (!unit || !Number.isFinite(unit.current) || !Number.isFinite(unit.total))
    return null;
  if (unit.total <= 0) return null;
  return Math.max(0, Math.min(100, Math.round((unit.current / unit.total) * 100)));
}

/** 当前项进度：视频/下载既显示 current/total，也显示百分比。 */
export function unitText(unit?: LiveUnit | null): string {
  if (!unit) return "";
  const parts = [`${unit.current} / ${unit.total}`];
  if (unit.label) parts.unshift(unit.label);
  return parts.join(" · ");
}

/** 任务列表运行中行摘要：「正在… · 预计剩余 …」。 */
export function runningSummary(task: Task) {
  if (!active(task)) return null;
  return {
    activity: activityOf(task),
    eta: formatEta(task.live?.eta_seconds),
  };
}

/** 小窗优先选真正在运行的（running），其次其它活跃/暂停状态。 */
export function focusTask(tasks: Task[]): Task | undefined {
  const live = tasks.filter(
    (task) => active(task) || task.status === "paused",
  );
  return (
    live.find((task) => task.status === "running") ||
    live.find((task) => task.status !== "paused") ||
    live[0]
  );
}
