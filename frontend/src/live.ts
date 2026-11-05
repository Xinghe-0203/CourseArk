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

// —— T8.8 日志分页纯函数（TaskDrawer 检索逻辑的可测形态） ——

/** 合并日志页：按 id 去重追加（游标翻页可能与服务端窗口重叠）。 */
export function appendEventPage<T extends { id: number }>(
  current: T[],
  incoming: T[],
): T[] {
  const seen = new Set(current.map((event) => event.id));
  return [...current, ...incoming.filter((event) => !seen.has(event.id))];
}

/** 游标推进：next_after_id>0 说明服务端还有更多页。 */
export function moreAfter(_cursor: number, next: number | undefined): boolean {
  return (next ?? 0) > 0;
}

/** 日志级别档位 → 服务端 level 参数（all/problem 直传，其余原样）。 */
export function logLevelParam(stage: string): string | null {
  if (!stage || stage === "all") return null;
  return stage;
}

/** 逐题状态筛选：all 原样，其余按 status 过滤并去掉空组。 */
export function filterAnswerGroups<T extends { items: { status: string }[] }>(
  groups: T[],
  filter: string,
): T[] {
  if (filter === "all") return groups;
  return groups
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => item.status === filter),
    }))
    .filter((group) => group.items.length);
}
