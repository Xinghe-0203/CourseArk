import type { Course, Settings, Task } from "./types";

/** 课程任务点进度展示：已完成 x / y，待完成高亮，未同步/同步中提示。 */
export type MissionTone = "ok" | "pending" | "muted";
export interface MissionState {
  text: string;
  tone: MissionTone;
  percent: number;
  pending: number;
}
export function missionState(course: Course, syncing = false): MissionState {
  const all = Math.max(0, Number(course.mission_all) || 0),
    fn = Math.max(0, Number(course.mission_fn) || 0);
  if (syncing)
    return {
      text: "同步中…",
      tone: "muted",
      percent: 0,
      pending: Math.max(0, all - fn),
    };
  if (!all)
    return {
      text: course.synced_at ? "任务点未同步" : "等待同步",
      tone: "muted",
      percent: 0,
      pending: 0,
    };
  const pending = Math.max(0, all - fn);
  return {
    text: pending
      ? `已完成 ${fn} / ${all}，待完成 ${pending}`
      : `已完成 ${all} / ${all}`,
    tone: pending ? "pending" : "ok",
    percent: Math.min(100, Math.round((fn / all) * 100)),
    pending,
  };
}
/** 账号卡片顶部的任务点合计。 */
export function missionTotals(courses: Course[]) {
  return courses.reduce(
    (sum, course) => ({
      fn: sum.fn + Math.max(0, Number(course.mission_fn) || 0),
      all: sum.all + Math.max(0, Number(course.mission_all) || 0),
      synced: sum.synced || Boolean(course.synced_at),
    }),
    { fn: 0, all: 0, synced: false },
  );
}

/** 可续跑状态：中断、手动停止、失败。 */
export const RESUMABLE_STATUSES = ["interrupted", "stopped", "failed"];
const UNFINISHED_UNIT_STATUSES = ["running", "failed", "blocked", "skipped"];
/** 后端优先给 unfinished_units；老数据回退到 stats.work.units 统计。 */
export function unfinishedUnits(task: Task): number {
  if (
    typeof task.unfinished_units === "number" &&
    Number.isFinite(task.unfinished_units)
  )
    return Math.max(0, task.unfinished_units);
  const units = (task.stats as any)?.work?.units;
  if (!units || typeof units !== "object") return 0;
  return Object.values(units).filter((unit: any) =>
    UNFINISHED_UNIT_STATUSES.includes(String(unit?.status ?? "")),
  ).length;
}
export function canResume(task: Task): boolean {
  return RESUMABLE_STATUSES.includes(task.status);
}
export function resumableTasks(tasks: Task[]): Task[] {
  return tasks.filter((task) => canResume(task) && unfinishedUnits(task) > 0);
}
export function unfinishedTotal(tasks: Task[]): number {
  return resumableTasks(tasks).reduce(
    (sum, task) => sum + unfinishedUnits(task),
    0,
  );
}
/** 最近一条未完成任务，供总览提示条上的「继续执行」使用。 */
export function latestUnfinished(tasks: Task[]): Task | undefined {
  return resumableTasks(tasks).sort((a, b) => b.created_at - a.created_at)[0];
}

/** 用户点过「不再提醒」的任务 id（settings.ui.dismissed_resume_tasks）。 */
export function dismissedResumeTasks(settings?: Settings | null): string[] {
  const list = (settings as any)?.ui?.dismissed_resume_tasks;
  return Array.isArray(list) ? list.map((item) => String(item)) : [];
}
export function isResumeDismissed(
  task: Task,
  settings?: Settings | null,
): boolean {
  return dismissedResumeTasks(settings).includes(task.id);
}
/** 待提醒的续跑任务：排除已点过「不再提醒」的 id，新中断任务照常提醒。 */
export function visibleResumableTasks(
  tasks: Task[],
  settings?: Settings | null,
): Task[] {
  const dismissed = new Set(dismissedResumeTasks(settings));
  return resumableTasks(tasks).filter((task) => !dismissed.has(task.id));
}
export function visibleUnfinishedTotal(
  tasks: Task[],
  settings?: Settings | null,
): number {
  return visibleResumableTasks(tasks, settings).reduce(
    (sum, task) => sum + unfinishedUnits(task),
    0,
  );
}
export function visibleLatestUnfinished(
  tasks: Task[],
  settings?: Settings | null,
): Task | undefined {
  return visibleResumableTasks(tasks, settings).sort(
    (a, b) => b.created_at - a.created_at,
  )[0];
}
/** 追加一个「不再提醒」的任务 id：去重并保留最近 100 条（与后端上限一致）。 */
export function nextDismissedResumeTasks(
  settings: Settings | null | undefined,
  id: string,
): string[] {
  const current = dismissedResumeTasks(settings).filter(
    (item) => item !== id,
  );
  return [...current, id].slice(-100);
}
